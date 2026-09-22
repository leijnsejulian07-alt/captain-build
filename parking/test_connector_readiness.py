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
    assert evaluate(base())["blockers"] == ()
    # A forged persisted Ready cannot bypass disconnected/disabled state.
    assert evaluate(base(connected=False, ready=True))["ready"] is False
    assert "not_connected" in evaluate(base(connected=False, ready=True))["blockers"]
    assert evaluate(base(enabled=False, ready=True))["ready"] is False
    assert "disabled" in evaluate(base(enabled=False, ready=True))["blockers"]

    for auth in ("unknown", "expired", "invalid", "reauth_required", "not_required"):
        x = base(); x["health"] = dict(x["health"], auth_status=auth)
        out = evaluate(x)
        assert out["ready"] is False, auth
        assert "auth_unhealthy" in out["blockers"], auth
    # Provider/version health must be positively current. Unknown is not evidence
    # of compatibility and therefore cannot preserve Ready across provider changes.
    for version in ("unknown", "deprecated", "migration_required"):
        x = base(); x["health"] = dict(x["health"], provider_version_status=version)
        out = evaluate(x)
        assert out["ready"] is False, version
        assert "provider_compatibility_unverified" in out["blockers"], version
    x = base(); x["health"] = dict(x["health"], status="degraded")
    assert evaluate(x)["ready"] is False
    assert "health_unhealthy" in evaluate(x)["blockers"]

    # Local/no-auth connector requires explicit not_required health evidence.
    local = base(auth_method="none")
    local["health"] = dict(local["health"], auth_status="not_required")
    assert evaluate(local)["ready"] is True
    local["health"] = dict(local["health"], auth_status="unknown")
    assert evaluate(local)["ready"] is False

    # Unknown/malformed auth methods must not be coerced into a Ready no-auth
    # connector, even when all other health evidence looks healthy/current.
    for method in (None, "", "magic", 123):
        x = base(auth_method=method)
        x["health"] = dict(x["health"], auth_status="not_required")
        out = evaluate(x)
        assert out["ready"] is False, method
        assert out["auth_method"] == "none"
        assert "auth_method_invalid" in out["blockers"]

    # Blockers are fixed reason codes only: raw provider diagnostics, tokens and
    # machine-specific errors must never be reflected into Settings notices.
    x = base()
    x["health"] = {
        "status": "broken: token=super-secret",
        "auth_status": "expired: sk-secret",
        "provider_version_status": "unknown: C:\\Users\\Julian",
    }
    out = evaluate(x)
    assert out["ready"] is False
    assert out["blockers"] == (
        "auth_unhealthy", "health_unhealthy", "provider_compatibility_unverified"
    )
    assert "secret" not in repr(out["blockers"]).lower()
    assert "julian" not in repr(out["blockers"]).lower()

    # Permissions normalize deterministically; malformed values do not leak through.
    out = evaluate(base(permissions=["write", "read", "read", "", None]))
    assert out["permissions"] == ("read", "write")
    assert "token" not in repr(out).lower()
    print("CAPTAIN_CONNECTOR_READINESS_PASS")


if __name__ == "__main__":
    run()
