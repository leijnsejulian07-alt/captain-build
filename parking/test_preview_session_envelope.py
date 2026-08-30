import unittest
from preview_session_envelope import create_preview_session, assert_preview_access, transition_preview


class PreviewIsolationTests(unittest.TestCase):
    def make(self):
        return create_preview_session(session_id="p1", chat_id="c1", project_id="proj1",
                                      repo_scope=r"C:\repos\alpha", builder_session_id="b1")

    def test_exact_scope_allowed(self):
        s = self.make()
        assert_preview_access(s, chat_id="c1", project_id="proj1",
                              repo_scope=r"C:\repos\alpha", builder_session_id="b1")

    def test_cross_chat_denied(self):
        with self.assertRaises(PermissionError):
            assert_preview_access(self.make(), chat_id="c2", project_id="proj1",
                                  repo_scope=r"C:\repos\alpha", builder_session_id="b1")

    def test_cross_project_denied(self):
        with self.assertRaises(PermissionError):
            assert_preview_access(self.make(), chat_id="c1", project_id="proj2",
                                  repo_scope=r"C:\repos\alpha", builder_session_id="b1")

    def test_cross_repo_denied(self):
        with self.assertRaises(PermissionError):
            assert_preview_access(self.make(), chat_id="c1", project_id="proj1",
                                  repo_scope=r"C:\repos\beta", builder_session_id="b1")

    def test_cross_builder_session_denied(self):
        with self.assertRaises(PermissionError):
            assert_preview_access(self.make(), chat_id="c1", project_id="proj1",
                                  repo_scope=r"C:\repos\alpha", builder_session_id="b2")

    def test_path_like_ids_rejected(self):
        with self.assertRaises(ValueError):
            create_preview_session(session_id="../p", chat_id="c1", project_id="proj1",
                                   repo_scope="repo", builder_session_id="b1")

    def test_revision_cannot_move_backwards(self):
        s = transition_preview(self.make(), status="ready", revision=2)
        with self.assertRaises(ValueError):
            transition_preview(s, status="ready", revision=1)

    def test_terminal_session_cannot_restart(self):
        s = transition_preview(self.make(), status="stopped", revision=1)
        with self.assertRaises(ValueError):
            transition_preview(s, status="starting", revision=2)


if __name__ == "__main__":
    unittest.main()
