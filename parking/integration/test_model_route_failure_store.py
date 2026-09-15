from __future__ import annotations

from model_route_failure_policy import record_route_failure
from model_route_failure_store import RouteFailureStore, RouteFailureStoreError


def _failure(kind: str = "auth_invalid", *, observed_at_ms: int = 1_000, previous_state=None) -> dict:
    return record_route_failure(
        provider_id="local-provider",
        model_id="model-a",
        failure_kind=kind,
        observed_at_ms=observed_at_ms,
        previous_state=previous_state,
    )


def _receipt(kind: str = "auth_invalid", *, observed_at_ms: int = 2_000) -> dict:
    return {
        "schema_version": 1,
        "provider_id": "local-provider",
        "model_id": "model-a",
        "failure_kind": kind,
        "clear_authorized": True,
        "observed_at_ms": observed_at_ms,
        "secret_fields": [],
    }


def expect_error(fn) -> None:
    try:
        fn()
    except RouteFailureStoreError:
        return
    raise AssertionError("expected RouteFailureStoreError")


def main() -> None:
    store = RouteFailureStore()
    first = _failure()
    store.put(first)
    assert store.get("local-provider", "model-a") == first

    result = store.clear_after_recovery(receipt=_receipt(), expected_failure_state=first)
    assert result.cleared is True
    assert result.provider_id == "local-provider"
    assert result.model_id == "model-a"
    assert store.get("local-provider", "model-a") is None

    # A stale receipt/snapshot cannot clear a newer route failure that arrived after recovery authorization.
    store.put(first)
    newer = _failure(observed_at_ms=1_500, previous_state=first)
    store.put(newer)
    expect_error(lambda: store.clear_after_recovery(receipt=_receipt(), expected_failure_state=first))
    assert store.get("local-provider", "model-a") == newer

    # Clearing requires exact route, kind and fresh success evidence.
    wrong_route = dict(_receipt(), model_id="model-b")
    expect_error(lambda: store.clear_after_recovery(receipt=wrong_route, expected_failure_state=newer))
    wrong_kind = dict(_receipt(), failure_kind="permission_denied")
    expect_error(lambda: store.clear_after_recovery(receipt=wrong_kind, expected_failure_state=newer))
    stale_success = _receipt(observed_at_ms=1_500)
    expect_error(lambda: store.clear_after_recovery(receipt=stale_success, expected_failure_state=newer))
    assert store.get("local-provider", "model-a") == newer

    # Receipts fail closed on schema expansion, secret-bearing metadata and false authorization.
    unknown = dict(_receipt())
    unknown["extra"] = "nope"
    expect_error(lambda: store.clear_after_recovery(receipt=unknown, expected_failure_state=newer))
    secret = dict(_receipt(), secret_fields=["api_key"])
    expect_error(lambda: store.clear_after_recovery(receipt=secret, expected_failure_state=newer))
    denied = dict(_receipt(), clear_authorized=False)
    expect_error(lambda: store.clear_after_recovery(receipt=denied, expected_failure_state=newer))

    # Failure state writes are monotone for one exact route.
    expect_error(lambda: store.put(newer))
    older = _failure(observed_at_ms=1_400)
    expect_error(lambda: store.put(older))
    assert store.get("local-provider", "model-a") == newer

    # Failed clear attempts are non-destructive; the valid exact current snapshot still clears.
    final_receipt = _receipt(observed_at_ms=2_500)
    result = store.clear_after_recovery(receipt=final_receipt, expected_failure_state=newer)
    assert result.cleared is True
    assert store.get("local-provider", "model-a") is None

    # Replaying a successful receipt after deletion fails closed rather than pretending success.
    expect_error(lambda: store.clear_after_recovery(receipt=final_receipt, expected_failure_state=newer))

    print("model route failure store regression: PASS")


if __name__ == "__main__":
    main()
