import unittest

from connector_authorization_gate import ConnectorAuthorizationError, authorize_connector_action
from connector_state_scope import bind_connector_state


def ready_state():
    return {
        "schema_version": 1,
        "connector_id": "github",
        "project_id": "project-a",
        "installed": True,
        "connected": True,
        "enabled": True,
        "ready": True,
        "auth_method": "oauth",
        "health": "healthy",
        "permissions_granted": ["read", "repo"],
        "permissions_required": ["read", "repo"],
        "issue_code": None,
    }


def bind(state=None):
    return bind_connector_state(
        state or ready_state(),
        chat_id="chat-a",
        project_id="project-a",
        repo_scope="owner/repo",
    )


def authorize(envelope, **overrides):
    args = {
        "chat_id": "chat-a",
        "project_id": "project-a",
        "repo_scope": "owner/repo",
        "connector_id": "github",
        "action": "repo",
    }
    args.update(overrides)
    return authorize_connector_action(envelope, **args)


class ConnectorAuthorizationGateTests(unittest.TestCase):
    def test_ready_scoped_action_is_authorized(self):
        result = authorize(bind())
        self.assertTrue(result["authorized"])
        self.assertEqual(result["permission"], "repo")

    def test_cross_project_replay_fails_closed(self):
        with self.assertRaises(ConnectorAuthorizationError):
            authorize(bind(), project_id="project-b")

    def test_connector_mismatch_fails_closed(self):
        with self.assertRaises(ConnectorAuthorizationError):
            authorize(bind(), connector_id="gmail")

    def test_disabled_connector_fails_closed(self):
        state = ready_state()
        state.update(enabled=False, ready=False)
        with self.assertRaises(ConnectorAuthorizationError):
            authorize(bind(state))

    def test_not_ready_connector_fails_closed(self):
        state = ready_state()
        state.update(ready=False, health="setup_required", issue_code="setup_version_changed")
        with self.assertRaises(ConnectorAuthorizationError):
            authorize(bind(state))

    def test_permission_not_granted_fails_closed(self):
        state = ready_state()
        state["permissions_granted"] = ["read"]
        state["ready"] = False
        with self.assertRaises(ConnectorAuthorizationError):
            authorize(bind(state))

    def test_action_outside_configured_permission_set_fails_closed(self):
        state = ready_state()
        state["permissions_granted"] = ["read", "repo", "browser"]
        state["permissions_required"] = ["read", "repo"]
        with self.assertRaises(ConnectorAuthorizationError):
            authorize(bind(state), action="browser")

    def test_unknown_action_fails_closed(self):
        with self.assertRaises(ConnectorAuthorizationError):
            authorize(bind(), action="shell")

    def test_tampered_envelope_fails_closed(self):
        envelope = bind()
        envelope["state"]["permissions_granted"].append("browser")
        with self.assertRaises(ConnectorAuthorizationError):
            authorize(envelope)


if __name__ == "__main__":
    unittest.main()
