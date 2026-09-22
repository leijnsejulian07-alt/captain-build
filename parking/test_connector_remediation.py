"""Regression checks for Captain connector Settings remediation."""
from connector_readiness import evaluate
from connector_remediation import remediation


def healthy(**overrides):
    c = {
        "connector_id": "github",
        "installed": True,
        "connected": True,
        "enabled": True,
        "auth_method": "oauth",
        "permissions": ["repo:read"],
        "health": {
            "status": "healthy",
            "auth_status": "valid",
            "provider_version_status": "current",
        },
    }
    c.update(overrides)
    return c


def test_ready_has_no_actions():
    assert remediation(evaluate(healthy())) == ()


def test_order_and_deep_links_are_stable():
    actions = remediation({
        "connector_id": "github",
        "ready": False,
        "blockers": ("not_connected", "auth_unhealthy", "provider_compatibility_unverified"),
    })
    assert [a["action"] for a in actions] == ["connect", "reconnect", "review_provider"]
    assert all(a["deep_link"] == "settings/connectors/github" for a in actions)


def test_expired_auth_maps_to_reconnect_without_provider_text():
    c = healthy()
    c["health"] = {
        "status": "healthy",
        "auth_status": "expired",
        "provider_version_status": "current",
        "provider_error": "token=super-secret C:/Users/private/key.txt",
    }
    actions = remediation(evaluate(c))
    assert [a["action"] for a in actions] == ["reconnect"]
    rendered = repr(actions)
    assert "super-secret" not in rendered
    assert "C:/Users" not in rendered


def test_unknown_provider_version_fails_closed_to_review():
    c = healthy()
    c["health"] = {
        "status": "healthy",
        "auth_status": "valid",
        "provider_version_status": "unknown",
    }
    state = evaluate(c)
    assert state["ready"] is False
    assert [a["action"] for a in remediation(state)] == ["review_provider"]


def test_malformed_auth_method_cannot_become_ready():
    state = evaluate(healthy(auth_method="future_magic_auth"))
    assert state["ready"] is False
    assert "auth_method_invalid" in state["blockers"]
    assert remediation(state)[0]["action"] == "review_setup"


def test_unknown_blocker_fails_closed_without_reflecting_payload():
    injected = "token=SECRET C:\\Users\\name\\key.txt"
    actions = remediation({"connector_id": "x", "ready": False, "blockers": (injected,)})
    assert actions[0]["reason"] == "unknown_blocker"
    assert actions[0]["action"] == "review_setup"
    assert injected not in repr(actions)
    assert "SECRET" not in repr(actions)


def test_malformed_blockers_do_not_become_actions():
    assert remediation({"connector_id": "x", "ready": False, "blockers": "auth_unhealthy"}) == ()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"CAPTAIN_CONNECTOR_REMEDIATION_PASS {len(tests)}")
