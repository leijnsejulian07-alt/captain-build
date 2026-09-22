import unittest
from builder_publication_guard import PublicationAuthority, PublicationDenied, authorize_publication


class BuilderPublicationGuardTests(unittest.TestCase):
    def setUp(self):
        self.a = PublicationAuthority("chat-a", "project-a", "repo-a", "session-a", 7, 3)
        self.diff = {"src/app.py": "v2"}

    def mutate(self, **kw):
        d = self.a.__dict__.copy(); d.update(kw); return PublicationAuthority(**d)

    def deny(self, current=None, diff=None, reviewed=True):
        with self.assertRaises(PublicationDenied):
            authorize_publication(session=self.a, current=current or self.a,
                                  diff=self.diff if diff is None else diff, reviewed=reviewed)

    def test_current_authority_and_reviewed_diff_can_publish(self):
        self.assertEqual(authorize_publication(session=self.a, current=self.a,
                                               diff=self.diff, reviewed=True), ("src/app.py",))

    def test_each_authority_wall_is_revalidated_at_publish_time(self):
        for current in (self.mutate(chat_id="chat-b"), self.mutate(project_id="project-b"),
                        self.mutate(repo_scope="repo-b"), self.mutate(builder_session_id="session-b"),
                        self.mutate(state_epoch=8), self.mutate(checkpoint=4)):
            self.deny(current=current)

    def test_epoch_change_revokes_previously_reviewed_publication(self):
        self.deny(current=self.mutate(state_epoch=8))

    def test_new_builder_checkpoint_requires_fresh_review(self):
        self.deny(current=self.mutate(checkpoint=4))
        self.deny(reviewed=False)

    def test_empty_or_unreviewed_diff_fails_closed(self):
        self.deny(diff={})
        self.deny(reviewed=False)
        self.deny(reviewed=1)

    def test_diff_paths_cannot_escape_repo_scope(self):
        for path in ("../secret", "/abs", "a//b", "a/./b", "a/../b", "C:/secret", "a\\b", ""):
            self.deny(diff={path: "x"})

    def test_malformed_authority_fails_closed(self):
        for current in (self.mutate(chat_id=""), self.mutate(repo_scope=" "),
                        self.mutate(state_epoch=True), self.mutate(state_epoch=-1),
                        self.mutate(checkpoint=True), self.mutate(checkpoint=-1)):
            self.deny(current=current)


if __name__ == "__main__":
    unittest.main()
