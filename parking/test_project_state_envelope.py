import unittest
from project_state_envelope import make_envelope, assert_same_scope


class ProjectStateEnvelopeTests(unittest.TestCase):
    def test_valid_scope(self):
        e = make_envelope(project_id="p1", repo_scope=r"C:\repo-a", kind="plan", revision=0, payload={"goal": "x"})
        assert_same_scope(e, project_id="p1", repo_scope=r"C:\repo-a")
        self.assertNotIn("repo-a", e.repo_scope_hash)

    def test_cross_project_denied(self):
        e = make_envelope(project_id="p1", repo_scope="repo-a", kind="task", revision=1, payload={})
        with self.assertRaises(PermissionError):
            assert_same_scope(e, project_id="p2", repo_scope="repo-a")

    def test_cross_repo_denied(self):
        e = make_envelope(project_id="p1", repo_scope="repo-a", kind="review", revision=1, payload={})
        with self.assertRaises(PermissionError):
            assert_same_scope(e, project_id="p1", repo_scope="repo-b")

    def test_missing_scope_denied(self):
        with self.assertRaises(ValueError):
            make_envelope(project_id="p1", repo_scope="", kind="plan", revision=0, payload={})

    def test_path_like_project_id_denied(self):
        with self.assertRaises(ValueError):
            make_envelope(project_id="../p1", repo_scope="repo", kind="plan", revision=0, payload={})

    def test_unknown_kind_denied(self):
        with self.assertRaises(ValueError):
            make_envelope(project_id="p1", repo_scope="repo", kind="shell", revision=0, payload={})

    def test_secret_shape_denied(self):
        for key in ("token", "api_key", "authorization", "cookie", "chat_id", "repo_scope"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                make_envelope(project_id="p1", repo_scope="repo", kind="research", revision=0, payload={key: "secret"})

    def test_boolean_revision_denied(self):
        with self.assertRaises(ValueError):
            make_envelope(project_id="p1", repo_scope="repo", kind="plan", revision=True, payload={})


if __name__ == "__main__":
    unittest.main()
