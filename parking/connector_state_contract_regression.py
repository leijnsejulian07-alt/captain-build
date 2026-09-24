"""Regression checks for Captain connector readiness -> canonical state compatibility.

Run locally with: python parking/connector_state_contract_regression.py
Requires jsonschema only for this parking regression; no network/auth/provider calls occur.
"""
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from connector_readiness import evaluate

HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "connector_state_contract.v1.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def assert_valid(value):
    errors = sorted(VALIDATOR.iter_errors(value), key=lambda e: list(e.path))
    assert not errors, "\n".join(error.message for error in errors)


def main():
    ready = evaluate({
        "connector_id": "github",
        "installed": True,
        "connected": True,
        "enabled": True,
        "auth_method": "oauth",
        "permissions": ["repo.read"],
        "health": {
            "status": "healthy",
            "checked_at": "2026-09-24T14:00:00Z",
            "auth_status": "valid",
            "provider_version_status": "current",
        },
    })
    # JSON is the actual Settings/control-plane boundary. Round-trip catches tuple/list
    # representation differences while ensuring the emitted public shape is canonical.
    assert_valid(json.loads(json.dumps(ready)))
    assert ready["ready"] is True and ready["blockers"] == ()

    blocked = evaluate({
        "connector_id": "github",
        "installed": True,
        "connected": True,
        "enabled": True,
        "auth_method": "oauth",
        "permissions": [],
        "health": {
            "status": "healthy",
            "checked_at": None,
            "auth_status": "expired",
            "provider_version_status": "migration_required",
        },
    })
    assert_valid(json.loads(json.dumps(blocked)))
    assert set(blocked["blockers"]) == {"auth_unhealthy", "provider_compatibility_unverified"}

    # Provider timestamps are metadata, not authority. Invalid/calendar-impossible or
    # diagnostic-bearing values must not escape into canonical Settings state.
    for bad_timestamp in (
        "not-a-date",
        "2026-02-31T14:00:00Z",
        "2026-09-24 14:00:00Z",
        "token=do-not-reflect",
    ):
        candidate = {
            "connector_id": "github", "installed": True, "connected": True,
            "enabled": True, "auth_method": "oauth", "permissions": [],
            "health": {"status": "healthy", "checked_at": bad_timestamp,
                       "auth_status": "valid", "provider_version_status": "current"},
        }
        normalized = evaluate(candidate)
        assert normalized["health"]["checked_at"] is None
        assert_valid(json.loads(json.dumps(normalized)))

    # Contract remains closed to arbitrary diagnostics/secrets even though blockers
    # are now part of the canonical public state.
    hostile = json.loads(json.dumps(blocked))
    hostile["blockers"] = ["token=do-not-reflect"]
    assert list(VALIDATOR.iter_errors(hostile))

    # Ensure format validation is genuinely active in this regression harness.
    hostile_time = json.loads(json.dumps(ready))
    hostile_time["health"]["checked_at"] = "not-a-date"
    assert list(VALIDATOR.iter_errors(hostile_time))

    print("PASS connector state contract regression")


if __name__ == "__main__":
    main()
