import unittest
from sandbox_provider_contract import SandboxRequest, SandboxScope


class SandboxProviderContractTests(unittest.TestCase):
    def setUp(self):
        self.scope = SandboxScope("chat-a", "project-a", "repo-a", 7, "builder-a")
        self.req = SandboxRequest.issue("local", "exec", self.scope)

    def test_exact_scope_authorizes(self):
        self.assertTrue(self.req.authorize(provider_id="local", action="exec", current_scope=self.scope))

    def test_cross_project_denied(self):
        other = SandboxScope("chat-a", "project-b", "repo-a", 7, "builder-a")
        self.assertFalse(self.req.authorize(provider_id="local", action="exec", current_scope=other))

    def test_cross_repo_denied(self):
        other = SandboxScope("chat-a", "project-a", "repo-b", 7, "builder-a")
        self.assertFalse(self.req.authorize(provider_id="local", action="exec", current_scope=other))

    def test_cross_chat_denied(self):
        other = SandboxScope("chat-b", "project-a", "repo-a", 7, "builder-a")
        self.assertFalse(self.req.authorize(provider_id="local", action="exec", current_scope=other))

    def test_stale_epoch_denied(self):
        other = SandboxScope("chat-a", "project-a", "repo-a", 8, "builder-a")
        self.assertFalse(self.req.authorize(provider_id="local", action="exec", current_scope=other))

    def test_other_builder_session_denied(self):
        other = SandboxScope("chat-a", "project-a", "repo-a", 7, "builder-b")
        self.assertFalse(self.req.authorize(provider_id="local", action="exec", current_scope=other))

    def test_provider_and_action_are_bound(self):
        self.assertFalse(self.req.authorize(provider_id="cloud", action="exec", current_scope=self.scope))
        self.assertFalse(self.req.authorize(provider_id="local", action="destroy", current_scope=self.scope))

    def test_unknown_action_cannot_be_issued(self):
        with self.assertRaises(ValueError):
            SandboxRequest.issue("local", "shell-anything", self.scope)

    def test_invalid_epoch_rejected(self):
        with self.assertRaises(ValueError):
            SandboxScope("c", "p", "r", -1, "b")
        with self.assertRaises(ValueError):
            SandboxScope("c", "p", "r", True, "b")


if __name__ == "__main__":
    unittest.main()
