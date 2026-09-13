import unittest

from reconciliation_scope_contract import bind_state, compute_scope_digest, unwrap_state, validate_scoped_state


class ReconciliationScopeContractTests(unittest.TestCase):
    def setUp(self):
        self.scope = dict(chat_id="chat-a", project_id="project-a", repo_scope="owner/repo")
        self.state = {"schema_version": 4, "local_base_sha": "a" * 40, "components": {}}

    def test_roundtrip_same_scope(self):
        envelope = bind_state(self.state, **self.scope)
        validate_scoped_state(envelope, **self.scope)
        self.assertEqual(unwrap_state(envelope, **self.scope), self.state)

    def test_project_mismatch_fails_closed(self):
        envelope = bind_state(self.state, **self.scope)
        with self.assertRaises(ValueError):
            validate_scoped_state(envelope, chat_id="chat-a", project_id="project-b", repo_scope="owner/repo")

    def test_chat_mismatch_fails_closed(self):
        envelope = bind_state(self.state, **self.scope)
        with self.assertRaises(ValueError):
            unwrap_state(envelope, chat_id="chat-b", project_id="project-a", repo_scope="owner/repo")

    def test_repo_scope_mismatch_fails_closed(self):
        envelope = bind_state(self.state, **self.scope)
        with self.assertRaises(ValueError):
            unwrap_state(envelope, chat_id="chat-a", project_id="project-a", repo_scope="owner/other")

    def test_tampered_digest_fails_closed(self):
        envelope = bind_state(self.state, **self.scope)
        envelope["scope_digest"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_scoped_state(envelope, **self.scope)

    def test_unknown_fields_and_old_schema_fail_closed(self):
        envelope = bind_state(self.state, **self.scope)
        envelope["extra"] = True
        with self.assertRaises(ValueError):
            validate_scoped_state(envelope, **self.scope)
        envelope = bind_state(self.state, **self.scope)
        envelope["schema_version"] = 0
        with self.assertRaises(ValueError):
            validate_scoped_state(envelope, **self.scope)

    def test_scope_values_are_normalized_and_bounded(self):
        a = compute_scope_digest(chat_id=" chat-a ", project_id="project-a", repo_scope="owner/repo")
        b = compute_scope_digest(**self.scope)
        self.assertEqual(a, b)
        for bad in ("", "   ", "x" * 513, "bad\x00scope"):
            with self.assertRaises(ValueError):
                compute_scope_digest(chat_id=bad, project_id="project-a", repo_scope="owner/repo")

    def test_state_is_deep_copied(self):
        envelope = bind_state(self.state, **self.scope)
        self.state["components"]["x"] = {"state": "pending"}
        self.assertNotIn("x", envelope["state"]["components"])
        result = unwrap_state(envelope, **self.scope)
        result["components"]["y"] = {"state": "pending"}
        self.assertNotIn("y", envelope["state"]["components"])


if __name__ == "__main__":
    unittest.main()
