from __future__ import annotations

from datetime import datetime, timezone
import tempfile

from connector_health_runtime import build_test_connection_request
from connector_notice_runtime import ConnectorNoticeStore
from connector_settings_contract import ContractError
from model_route_connector_bridge import apply_route_failure_to_connector
from model_route_failure_policy import record_route_failure
from model_route_recovery_bridge import recover_route_after_test_connection


def _state(connector_id: str = "local-provider") -> dict:
    return {
        "schema_version": 1,
        "connector_id": connector_id,
        "project_id": "project-a",
        "installed": True,
        "connected": True,
        "enabled": True,
        "ready": True,
        "auth_method": "api_key",
        "health": "healthy",
        "permissions_granted": ["read"],
        "permissions_required": ["read"],
        "issue_code": None,
    }


def _failure(kind: str, *, provider_id: str = "local-provider", observed_at_ms: int = 1_000) -> dict:
    kwargs = {
        "provider_id": provider_id,
        "model_id": "model-a",
        "failure_kind": kind,
        "observed_at_ms": observed_at_ms,
    }
    if kind == "rate_limited":
        kwargs["retry_after_ms"] = 10_000
    return record_route_failure(**kwargs)


def _probe(request: dict, observed_at: datetime, **overrides) -> dict:
    probe = {
        "schema_version": 1,
        "connector_id": request["connector_id"],
        "project_id": request["project_id"],
        "auth_method": request["auth_method"],
        "observed_at": observed_at.isoformat(),
        "provider_status": "reachable",
        "auth_status": "valid",
        "permissions_granted": ["read"],
        "request_digest": request["request_digest"],
        "secret_fields": [],
    }
    probe.update(overrides)
    return probe


def expect_contract_error(fn) -> None:
    try:
        fn()
    except ContractError:
        return
    raise AssertionError("expected ContractError")


def main() -> None:
    requested_at = datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc)
    observed_at = datetime(2026, 9, 14, 20, 0, 2, tzinfo=timezone.utc)
    now = datetime(2026, 9, 14, 20, 0, 3, tzinfo=timezone.utc)
    remediation = "settings://connectors/local-provider"

    for kind in ("auth_invalid", "permission_denied", "setup_required"):
        failure = _failure(kind)
        projected = apply_route_failure_to_connector(_state(), failure)
        assert projected["ready"] is False
        request = build_test_connection_request(projected, requested_at)
        probe = _probe(request, observed_at)
        with tempfile.TemporaryDirectory() as tmp:
            store = ConnectorNoticeStore(f"{tmp}/notices.sqlite3")
            notice = store.evaluate(projected, remediation, requested_at)
            assert notice is not None
            assert len(store.persisted_rows()) == 1

            recovered, receipt = recover_route_after_test_connection(
                projected,
                failure,
                request=request,
                probe=probe,
                notice_store=store,
                remediation_path=remediation,
                now=now,
            )
            assert recovered["ready"] is True
            assert recovered["health"] == "healthy"
            assert recovered["issue_code"] is None
            assert recovered["installed"] is True
            assert recovered["connected"] is True
            assert recovered["enabled"] is True
            assert recovered["auth_method"] == "api_key"
            assert recovered["permissions_required"] == ["read"]
            assert recovered["permissions_granted"] == ["read"]
            assert receipt == {
                "schema_version": 1,
                "provider_id": "local-provider",
                "model_id": "model-a",
                "failure_kind": kind,
                "clear_authorized": True,
                "observed_at_ms": int(observed_at.timestamp() * 1000),
                "secret_fields": [],
            }
            assert store.persisted_rows() == []

    # Generic connector tests may not clear deprecation or cooldown state.
    for kind in ("provider_deprecated", "transient", "rate_limited"):
        failure = _failure(kind)
        projected = apply_route_failure_to_connector(_state(), failure)
        request = build_test_connection_request(projected, requested_at)
        probe = _probe(request, observed_at)
        with tempfile.TemporaryDirectory() as tmp:
            store = ConnectorNoticeStore(f"{tmp}/notices.sqlite3")
            expect_contract_error(lambda: recover_route_after_test_connection(
                projected,
                failure,
                request=request,
                probe=probe,
                notice_store=store,
                remediation_path=remediation,
                now=now,
            ))

    # An unsuccessful Test Connection never authorizes route-state deletion and keeps the notice.
    failure = _failure("auth_invalid")
    projected = apply_route_failure_to_connector(_state(), failure)
    request = build_test_connection_request(projected, requested_at)
    invalid_probe = _probe(request, observed_at, auth_status="invalid")
    with tempfile.TemporaryDirectory() as tmp:
        store = ConnectorNoticeStore(f"{tmp}/notices.sqlite3")
        store.evaluate(projected, remediation, requested_at)
        expect_contract_error(lambda: recover_route_after_test_connection(
            projected,
            failure,
            request=request,
            probe=invalid_probe,
            notice_store=store,
            remediation_path=remediation,
            now=now,
        ))
        assert len(store.persisted_rows()) == 1

    # Scope, request integrity and secret-bearing probe mutations fail closed.
    other_failure = _failure("auth_invalid", provider_id="other-provider")
    request = build_test_connection_request(projected, requested_at)
    good_probe = _probe(request, observed_at)
    with tempfile.TemporaryDirectory() as tmp:
        store = ConnectorNoticeStore(f"{tmp}/notices.sqlite3")
        expect_contract_error(lambda: recover_route_after_test_connection(
            projected,
            other_failure,
            request=request,
            probe=good_probe,
            notice_store=store,
            remediation_path=remediation,
            now=now,
        ))

        bad_digest_probe = dict(good_probe, request_digest="0" * 64)
        expect_contract_error(lambda: recover_route_after_test_connection(
            projected,
            failure,
            request=request,
            probe=bad_digest_probe,
            notice_store=store,
            remediation_path=remediation,
            now=now,
        ))

        secret_probe = dict(good_probe)
        secret_probe["api_key"] = "must-not-cross-boundary"
        expect_contract_error(lambda: recover_route_after_test_connection(
            projected,
            failure,
            request=request,
            probe=secret_probe,
            notice_store=store,
            remediation_path=remediation,
            now=now,
        ))

    # Test evidence must be newer than the route failure it is attempting to clear.
    late_failure = _failure(
        "auth_invalid",
        observed_at_ms=int((observed_at.timestamp() + 1) * 1000),
    )
    late_projected = apply_route_failure_to_connector(_state(), late_failure)
    late_request = build_test_connection_request(late_projected, requested_at)
    late_probe = _probe(late_request, observed_at)
    with tempfile.TemporaryDirectory() as tmp:
        store = ConnectorNoticeStore(f"{tmp}/notices.sqlite3")
        expect_contract_error(lambda: recover_route_after_test_connection(
            late_projected,
            late_failure,
            request=late_request,
            probe=late_probe,
            notice_store=store,
            remediation_path=remediation,
            now=now,
        ))

    print("model route recovery bridge regression: PASS")


if __name__ == "__main__":
    main()
