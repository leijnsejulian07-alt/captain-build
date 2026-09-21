import unittest
from project_memory_epoch_guard import ActiveScope, ScopeDenied, authorize_project_envelope, project_memory_for_chat


def env(*, chat="c1", project="p1", epoch=7, repo=None, kind="project_memory"):
    return {"version": 1, "kind": kind, "scope": {"chat_id": chat, "project_id": project, "state_epoch": epoch, "repo_scope": repo}, "created_at": "2026-09-21T18:00:00Z", "payload": {"fact": "scoped"}}


class ProjectMemoryEpochGuardTests(unittest.TestCase):
    def setUp(self):
        self.active = ActiveScope("c1", "p1", 7, "owner/repo")

    def test_current_scope_is_readable(self):
        self.assertEqual(authorize_project_envelope(env(repo="owner/repo"), self.active)["fact"], "scoped")

    def test_stale_epoch_is_inaccessible(self):
        with self.assertRaises(ScopeDenied):
            authorize_project_envelope(env(epoch=6, repo="owner/repo"), self.active)

    def test_future_epoch_is_also_inaccessible(self):
        with self.assertRaises(ScopeDenied):
            authorize_project_envelope(env(epoch=8, repo="owner/repo"), self.active)

    def test_cross_chat_project_and_repo_are_inaccessible(self):
        for candidate in (env(chat="c2", repo="owner/repo"), env(project="p2", repo="owner/repo"), env(repo="owner/other")):
            with self.subTest(candidate=candidate["scope"]), self.assertRaises(ScopeDenied):
                authorize_project_envelope(candidate, self.active)

    def test_repo_bound_memory_cannot_become_project_global(self):
        with self.assertRaises(ScopeDenied):
            authorize_project_envelope(env(repo="owner/repo"), ActiveScope("c1", "p1", 7, None))

    def test_malformed_data_fails_closed(self):
        for candidate in ({}, {"version": 1}, {"version": 1, "kind": "project_memory", "scope": {}, "payload": {}}):
            with self.subTest(candidate=candidate), self.assertRaises(ScopeDenied):
                authorize_project_envelope(candidate, self.active)

    def test_normal_non_project_chat_does_not_break_or_inherit_project_memory(self):
        self.assertIsNone(project_memory_for_chat(env(repo="owner/repo"), None))
        self.assertIsNone(project_memory_for_chat(None, None))

    def test_context_obeys_same_wall(self):
        with self.assertRaises(ScopeDenied):
            authorize_project_envelope(env(kind="project_context", epoch=6, repo="owner/repo"), self.active)


if __name__ == "__main__":
    unittest.main()
