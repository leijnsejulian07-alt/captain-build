import unittest
from repo_agent_loop import RepoAgentLoop


class RepoAgentLoopTests(unittest.TestCase):
    def make(self, **kw):
        args = dict(loop_id="loop-1", chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/a")
        args.update(kw)
        return RepoAgentLoop.create(**args)

    def test_happy_path(self):
        x = self.make()
        for stage in ("build", "test", "review", "done"):
            x = x.advance(stage, chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/a")
        self.assertEqual(x.stage, "done")
        self.assertEqual(x.revision, 4)

    def test_cross_chat_denied(self):
        with self.assertRaises(PermissionError):
            self.make().advance("build", chat_id="chat-2", project_id="proj-1", repo_scope="C:/repos/a")

    def test_cross_project_denied(self):
        with self.assertRaises(PermissionError):
            self.make().advance("build", chat_id="chat-1", project_id="proj-2", repo_scope="C:/repos/a")

    def test_cross_repo_denied(self):
        with self.assertRaises(PermissionError):
            self.make().advance("build", chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/b")

    def test_invalid_transition_denied(self):
        with self.assertRaises(ValueError):
            self.make().advance("review", chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/a")

    def test_debug_budget_bounded(self):
        x = self.make(max_debug_cycles=1)
        x = x.advance("build", chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/a")
        x = x.advance("test", chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/a")
        x = x.advance("debug", chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/a")
        x = x.advance("test", chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/a")
        with self.assertRaises(ValueError):
            x.advance("debug", chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/a")

    def test_terminal_not_reused(self):
        x = self.make().advance("failed", chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/a")
        with self.assertRaises(ValueError):
            x.advance("build", chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/a")

    def test_path_like_ids_rejected(self):
        for bad in ("../loop", "a/b", "", "x" * 65):
            with self.assertRaises(ValueError):
                self.make(loop_id=bad)

    def test_public_state_has_no_raw_scope(self):
        state = self.make().public_state()
        self.assertNotIn("repo_scope", state)
        self.assertNotIn("chat_id", state)
        self.assertNotIn("project_id", state)
        self.assertEqual(len(state["repo_scope_hash"]), 64)


if __name__ == "__main__":
    unittest.main()
