import unittest
from builder_artifact_envelope import create_artifact, can_access, transition, next_revision


class BuilderArtifactTests(unittest.TestCase):
    def make(self):
        return create_artifact(artifact_id="a1", chat_id="chat1", project_id="p1",
            repo_scope="C:/repo/a", builder_session_id="b1", kind="diff",
            revision=1, content=b"hello")

    def test_exact_scope_access(self):
        a = self.make()
        self.assertTrue(can_access(a, chat_id="chat1", project_id="p1",
            repo_scope="C:/repo/a", builder_session_id="b1"))

    def test_cross_chat_project_repo_builder_denied(self):
        a = self.make()
        variants = [("chat2","p1","C:/repo/a","b1"), ("chat1","p2","C:/repo/a","b1"),
                    ("chat1","p1","C:/repo/b","b1"), ("chat1","p1","C:/repo/a","b2")]
        for chat, project, repo, builder in variants:
            self.assertFalse(can_access(a, chat_id=chat, project_id=project,
                repo_scope=repo, builder_session_id=builder))

    def test_path_like_id_rejected(self):
        with self.assertRaises(ValueError):
            create_artifact(artifact_id="../escape", chat_id="c", project_id="p",
                repo_scope="repo", builder_session_id="b", kind="diff", revision=1, content=b"x")

    def test_unknown_kind_and_oversize_rejected(self):
        with self.assertRaises(ValueError):
            create_artifact(artifact_id="a", chat_id="c", project_id="p", repo_scope="repo",
                builder_session_id="b", kind="shell", revision=1, content=b"x")
        with self.assertRaises(ValueError):
            create_artifact(artifact_id="a", chat_id="c", project_id="p", repo_scope="repo",
                builder_session_id="b", kind="diff", revision=1, content=b"x" * 2_000_001)

    def test_revision_monotonic_and_scope_preserved(self):
        a = self.make(); b = next_revision(a, revision=2, content=b"changed")
        self.assertEqual(a.repo_scope_hash, b.repo_scope_hash)
        self.assertNotEqual(a.content_sha256, b.content_sha256)
        with self.assertRaises(ValueError): next_revision(b, revision=2, content=b"again")

    def test_lifecycle_and_terminal_reuse(self):
        a = transition(self.make(), "verified")
        committed = transition(a, "committed")
        with self.assertRaises(ValueError): transition(committed, "verified")
        with self.assertRaises(ValueError): next_revision(committed, revision=2, content=b"x")

    def test_bool_revision_rejected(self):
        with self.assertRaises(ValueError):
            create_artifact(artifact_id="a", chat_id="c", project_id="p", repo_scope="repo",
                builder_session_id="b", kind="diff", revision=True, content=b"x")


if __name__ == "__main__":
    unittest.main()
