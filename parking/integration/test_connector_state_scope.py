import unittest

from connector_state_scope import (
    ConnectorStateScopeError,
    bind_connector_state,
    unwrap_connector_state,
)


STATE = {
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


class ConnectorStateScopeTests(unittest.TestCase):
    def test_round_trip_exact_scope(self):
        env = bind_connector_state(STATE, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        self.assertEqual(
            unwrap_connector_state(env, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain"),
            STATE,
        )

    def test_cross_chat_replay_fails_closed(self):
        env = bind_connector_state(STATE, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        with self.assertRaises(ConnectorStateScopeError):
            unwrap_connector_state(env, chat_id="chat-b", project_id="project-a", repo_scope="repo:captain")

    def test_cross_project_replay_fails_closed(self):
        env = bind_connector_state(STATE, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        with self.assertRaises(ConnectorStateScopeError):
            unwrap_connector_state(env, chat_id="chat-a", project_id="project-b", repo_scope="repo:captain")

    def test_cross_repo_replay_fails_closed(self):
        env = bind_connector_state(STATE, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        with self.assertRaises(ConnectorStateScopeError):
            unwrap_connector_state(env, chat_id="chat-a", project_id="project-a", repo_scope="repo:other")

    def test_state_tampering_fails_closed(self):
        env = bind_connector_state(STATE, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        env["state"]["permissions_granted"] = ["admin"]
        with self.assertRaises(ConnectorStateScopeError):
            unwrap_connector_state(env, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")

    def test_unknown_envelope_field_fails_closed(self):
        env = bind_connector_state(STATE, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        env["extra"] = True
        with self.assertRaises(ConnectorStateScopeError):
            unwrap_connector_state(env, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")

    def test_bind_requires_matching_project(self):
        with self.assertRaises(ConnectorStateScopeError):
            bind_connector_state(STATE, chat_id="chat-a", project_id="project-b", repo_scope="repo:captain")

    def test_secret_like_fields_are_forbidden(self):
        for field in ("token", "access_token", "refresh_token", "api_key", "password", "secret", "secrets"):
            with self.subTest(field=field):
                bad = dict(STATE)
                bad[field] = "do-not-persist"
                with self.assertRaises(ConnectorStateScopeError):
                    bind_connector_state(bad, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")

    def test_returned_state_is_detached_copy(self):
        env = bind_connector_state(STATE, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        returned = unwrap_connector_state(env, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        returned["permissions_granted"].append("admin")
        self.assertEqual(env["state"]["permissions_granted"], ["read", "repo"])


if __name__ == "__main__":
    unittest.main()
