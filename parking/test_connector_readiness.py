"""Dependency-free regressions for connector_readiness.py."""
from connector_readiness import evaluate


def base(**updates):
    value = {
        "connector_id": "github",
        "installed": True,
        "connected": True,
        "enabled": True,
        "ready": False,  # persisted value must never be trusted
        "auth_method": "oauth",
        "permissions": ["repo:read"],
        "health": {
            "status": "healthy",
            "auth_status": "valid",
            "provider_version_status": "current",
        },
    }
    value.update(updates)
    return value


def run():
    assert evaluate(base())["ready"] is True
    # A forged persisted Ready cannot bypass disconnected/disabled state.
    assert evaluate(base(connected=False, ready=True))["ready"] is False
    assert evaluate(base(enabled=False, ready=True))["ready"] is False

    for auth in ("unknown", "expired", "invalid", "reauth_required", "not_required"):
        x = base(); x["health"] = dict(x["health"], auth_status=auth)
        assert evaluate(x)["ready"] is False, auth
    for version in ("deprecated", "migration_required"):
        x = base(); x["health"] = dict(x["health"], provider_version_status=version)
        assert evaluate(x)["ready"] is False, version
    x = base(); x["health"] = dict(x["health"], status="degraded")
    assert evaluate(x)["ready"] is False

    # Local/no-auth connector requires explicit not_required health evidence.
    local = base(auth_method="none")
    local["health"] = dict(local["health"], auth_status="not_required")
    assert evaluate(local)["ready"] is True
    local["health"] = dict(local["health"], auth_status="unknown")
    assert evaluate(local)["ready"] is False

    # Permissions normalize deterministically; malformed values do not leak through.
    out = evaluate(base(permissions=["write", "read", "read", "", None]))
    assert out["permissions"] == ("read", "write")
    assert "token" not in repr(out).lower()
    print("CAPTAIN_CONNECTOR_READINESS_PASS")


if __name__ == "__main__":
    run()
