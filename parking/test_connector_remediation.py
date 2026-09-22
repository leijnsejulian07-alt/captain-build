from connector_remediation import remediation


def test_ready_has_no_actions():
    assert remediation({"connector_id": "github", "ready": True, "blockers": ()}) == ()


def test_order_and_deep_links_are_stable():
    actions = remediation({
        "connector_id": "github",
        "ready": False,
        "blockers": ("not_connected", "auth_unhealthy", "provider_compatibility_unverified"),
    })
    assert [a["action"] for a in actions] == ["connect", "reconnect", "review_provider"]
    assert all(a["deep_link"] == "settings/connectors/github" for a in actions)


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
    test_ready_has_no_actions()
    test_order_and_deep_links_are_stable()
    test_unknown_blocker_fails_closed_without_reflecting_payload()
    test_malformed_blockers_do_not_become_actions()
    print("CAPTAIN_CONNECTOR_REMEDIATION_PASS")
