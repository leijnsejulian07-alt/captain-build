"""Dependency-free regressions for connector_readiness.py."""
from connector_readiness import evaluate


def base(**updates):
    value = {
        "connector_id": "github", "installed": True, "connected": True,
        "enabled": True, "ready": False, "auth_method": "oauth",
        "permissions": ["repo:read"],
        "health": {"status": "healthy", "auth_status": "valid", "provider_version_status": "current"},
    }
    value.update(updates)
    return value


def rejected(value, exc=(TypeError, ValueError)):
    try: evaluate(value)
    except exc: return
    raise AssertionError("malformed connector state accepted")


def run():
    assert evaluate(base())["ready"] is True
    assert evaluate(base())["blockers"] == ()
    assert evaluate(base(connected=False, ready=True))["ready"] is False
    assert "not_connected" in evaluate(base(connected=False, ready=True))["blockers"]
    assert evaluate(base(enabled=False, ready=True))["ready"] is False
    assert "disabled" in evaluate(base(enabled=False, ready=True))["blockers"]
    for auth in ("unknown", "expired", "invalid", "reauth_required", "not_required"):
        x = base(); x["health"] = dict(x["health"], auth_status=auth)
        out = evaluate(x); assert out["ready"] is False, auth
        assert "auth_unhealthy" in out["blockers"], auth
    for version in ("unknown", "deprecated", "migration_required"):
        x = base(); x["health"] = dict(x["health"], provider_version_status=version)
        out = evaluate(x); assert out["ready"] is False, version
        assert "provider_compatibility_unverified" in out["blockers"], version
    x = base(); x["health"] = dict(x["health"], status="degraded")
    assert evaluate(x)["ready"] is False
    local = base(auth_method="none"); local["health"] = dict(local["health"], auth_status="not_required")
    assert evaluate(local)["ready"] is True
    for method in (None, "", "magic", 123):
        x = base(auth_method=method); x["health"] = dict(x["health"], auth_status="not_required")
        out = evaluate(x); assert out["ready"] is False and "auth_method_invalid" in out["blockers"]

    # Unknown provider strings fail closed and are never reflected into UI state.
    x = base(); x["health"] = {"status": "broken: token=super-secret", "auth_status": "expired: sk-secret", "provider_version_status": "unknown: C:\\Users\\Julian"}
    out = evaluate(x); assert out["blockers"] == ("auth_unhealthy", "health_unhealthy", "provider_compatibility_unverified")
    assert out["health"] == {"status": "unknown", "auth_status": "unknown", "provider_version_status": "unknown"}
    assert "secret" not in repr(out).lower() and "julian" not in repr(out).lower()
    out = evaluate(base(permissions=["write", "read", "read", "", None]))
    assert out["permissions"] == ("read", "write")

    # Match the canonical connector-state schema's identifier and permission bounds.
    for bad_id in ("GitHub", "github/settings", "github?x=1", ".github", "github oauth", "x" * 129):
        rejected(base(connector_id=bad_id))
    rejected(base(permissions=["x" * 129]))
    rejected(base(permissions=["p"] * 129))
    assert evaluate(base(connector_id="github-enterprise.v2"))["connector_id"] == "github-enterprise.v2"

    touched = []
    class EvilDict(dict):
        def get(self, *args, **kwargs): touched.append("dict-get"); raise AssertionError("hostile dict hook executed")
    class EvilList(list):
        def __iter__(self): touched.append("list-iter"); raise AssertionError("hostile list hook executed")
    class EvilStr(str):
        def __eq__(self, other): touched.append("str-eq"); raise AssertionError("hostile string hook executed")
        def __hash__(self): touched.append("str-hash"); raise AssertionError("hostile string hook executed")
    rejected(EvilDict(base()))
    rejected(base(permissions=EvilList(["repo:read"])))
    rejected(base(health=EvilDict(base()["health"])))
    rejected(base(connector_id=EvilStr("github")))
    x = base(); x["health"] = dict(x["health"], status=EvilStr("healthy")); rejected(x)
    x = base(); x["health"] = dict(x["health"], auth_status=EvilStr("valid")); rejected(x)
    x = base(); x["health"] = dict(x["health"], provider_version_status=EvilStr("current")); rejected(x)
    assert touched == []

    # Bound provider-controlled scalar/cardinality inputs to avoid Settings DoS.
    for field in ("status", "auth_status", "provider_version_status"):
        x = base(); x["health"] = dict(x["health"], **{field: "x" * 257}); rejected(x)
    assert evaluate(base())["ready"] is True
    print("CAPTAIN_CONNECTOR_READINESS_PASS")


if __name__ == "__main__": run()
