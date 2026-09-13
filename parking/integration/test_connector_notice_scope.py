import unittest

from connector_notice_scope import ScopeError, bind_notice, unwrap_notice


NOTICE = {
    "schema_version": 1,
    "connector_id": "github",
    "project_id": "project-a",
    "issue_code": "reauth",
    "notice_fingerprint": "abc",
    "remediation_path": "settings://connectors/github",
    "dismiss_until": None,
    "secret_fields": [],
}


class ConnectorNoticeScopeTests(unittest.TestCase):
    def test_round_trip_exact_scope(self):
        env = bind_notice(NOTICE, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        self.assertEqual(unwrap_notice(env, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain"), NOTICE)

    def test_cross_chat_replay_fails_closed(self):
        env = bind_notice(NOTICE, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        with self.assertRaises(ScopeError):
            unwrap_notice(env, chat_id="chat-b", project_id="project-a", repo_scope="repo:captain")

    def test_cross_project_replay_fails_closed(self):
        env = bind_notice(NOTICE, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        with self.assertRaises(ScopeError):
            unwrap_notice(env, chat_id="chat-a", project_id="project-b", repo_scope="repo:captain")

    def test_cross_repo_replay_fails_closed(self):
        env = bind_notice(NOTICE, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        with self.assertRaises(ScopeError):
            unwrap_notice(env, chat_id="chat-a", project_id="project-a", repo_scope="repo:other")

    def test_notice_tampering_fails_closed(self):
        env = bind_notice(NOTICE, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        env["notice"]["issue_code"] = "different"
        with self.assertRaises(ScopeError):
            unwrap_notice(env, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")

    def test_unknown_envelope_field_fails_closed(self):
        env = bind_notice(NOTICE, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")
        env["extra"] = True
        with self.assertRaises(ScopeError):
            unwrap_notice(env, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")

    def test_secret_payload_contract_fails_closed(self):
        bad = dict(NOTICE, secret_fields=["token"])
        with self.assertRaises(ScopeError):
            bind_notice(bad, chat_id="chat-a", project_id="project-a", repo_scope="repo:captain")

    def test_bind_requires_matching_project(self):
        with self.assertRaises(ScopeError):
            bind_notice(NOTICE, chat_id="chat-a", project_id="project-b", repo_scope="repo:captain")


if __name__ == "__main__":
    unittest.main()
