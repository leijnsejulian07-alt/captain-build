from __future__ import annotations

from datetime import datetime, timezone
import tempfile

from connector_notice_runtime import ConnectorNoticeStore
from connector_settings_contract import ContractError, validate_connector_state
from model_route_connector_bridge import apply_route_failure_and_notice, apply_route_failure_to_connector
from model_route_failure_policy import record_route_failure


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


def _failure(kind: str, provider_id: str = "local-provider") -> dict:
    kwargs = {
        "provider_id": provider_id,
        "model_id": "model-a",
        "failure_kind": kind,
        "observed_at_ms": 1_000,
    }
    if kind == "rate_limited":
        kwargs["retry_after_ms"] = 10_000
    return record_route_failure(**kwargs)


def expect_contract_error(fn) -> None:
    try:
        fn()
    except ContractError:
        return
    raise AssertionError("expected ContractError")


def main() -> None:
    expected = {
        "transient": ("degraded", "provider_temporarily_unavailable"),
        "rate_limited": ("degraded", "provider_rate_limited"),
        "auth_invalid": ("invalid_auth", "credentials_invalid"),
        "permission_denied": ("setup_required", "permissions_denied"),
        "setup_required": ("setup_required", "provider_setup_required"),
        "provider_deprecated": ("deprecated", "provider_deprecated"),
    }
    original = _state()
    for kind, (health, issue) in expected.items():
        projected = apply_route_failure_to_connector(original, _failure(kind))
        validate_connector_state(projected)
        assert projected["ready"] is False
        assert projected["health"] == health
        assert projected["issue_code"] == issue
        for immutable in (
            "connector_id", "project_id", "installed", "connected", "enabled",
            "auth_method", "permissions_granted", "permissions_required",
        ):
            assert projected[immutable] == original[immutable]
        assert original["ready"] is True
        assert original["health"] == "healthy"
        assert original["issue_code"] is None

    expect_contract_error(lambda: apply_route_failure_to_connector(original, _failure("auth_invalid", "other-provider")))
    uninstalled = dict(original, installed=False, connected=False, enabled=False, ready=False, health="setup_required", issue_code="install_required")
    validate_connector_state(uninstalled)
    expect_contract_error(lambda: apply_route_failure_to_connector(uninstalled, _failure("setup_required")))

    # Strict route failure parsing rejects secret/unknown fields at the bridge boundary.
    tainted = dict(_failure("auth_invalid"))
    tainted["api_key"] = "must-not-cross-boundary"
    expect_contract_error(lambda: apply_route_failure_to_connector(original, tainted))

    now = datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        store = ConnectorNoticeStore(f"{tmp}/notices.sqlite3")
        projected, notice = apply_route_failure_and_notice(
            original,
            _failure("auth_invalid"),
            notice_store=store,
            remediation_path="settings://connectors/local-provider",
            now=now,
        )
        assert projected["health"] == "invalid_auth"
        assert notice is not None
        assert notice["connector_id"] == "local-provider"
        assert notice["project_id"] == "project-a"
        assert notice["issue_code"] == "credentials_invalid"
        assert notice["remediation_path"] == "settings://connectors/local-provider"
        assert notice["secret_fields"] == []
        rows = store.persisted_rows()
        assert len(rows) == 1
        # Persistent notice storage contains digests/timestamps, never raw connector/project IDs.
        persisted = " ".join(str(part) for part in rows[0])
        assert "local-provider" not in persisted
        assert "project-a" not in persisted

    print("model route connector bridge regression: PASS")


if __name__ == "__main__":
    main()
