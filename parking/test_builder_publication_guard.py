import unittest
from builder_publication_guard import (PublicationAuthority, PublicationDenied,
                                       authorize_publication, publication_digest)


class BuilderPublicationGuardTests(unittest.TestCase):
    def setUp(self):
        self.a = PublicationAuthority("chat-a", "project-a", "repo-a", "session-a", 7, 3)
        self.diff = {"src/app.py": "v2"}

    def mutate(self, **kw):
        d = self.a.__dict__.copy(); d.update(kw); return PublicationAuthority(**d)

    def digest(self, authority=None, diff=None):
        return publication_digest(authority=authority or self.a, diff=self.diff if diff is None else diff)

    def deny(self, current=None, diff=None, digest=None):
        current = current or self.a
        diff = self.diff if diff is None else diff
        if digest is None:
            digest = self.digest()
        with self.assertRaises(PublicationDenied):
            authorize_publication(session=self.a, current=current, diff=diff, reviewed_digest=digest)

    def test_current_authority_and_exact_reviewed_diff_can_publish(self):
        self.assertEqual(authorize_publication(session=self.a, current=self.a, diff=self.diff,
                                               reviewed_digest=self.digest()), ("src/app.py",))

    def test_each_authority_wall_is_revalidated_at_publish_time(self):
        for current in (self.mutate(chat_id="chat-b"), self.mutate(project_id="project-b"),
                        self.mutate(repo_scope="repo-b"), self.mutate(builder_session_id="session-b"),
                        self.mutate(state_epoch=8), self.mutate(checkpoint=4)):
            self.deny(current=current)

    def test_diff_mutation_after_review_is_denied(self):
        approved = self.digest()
        self.deny(diff={"src/app.py": "v3"}, digest=approved)
        self.deny(diff={"src/app.py": "v2", "src/extra.py": "surprise"}, digest=approved)

    def test_path_mutation_after_review_is_denied(self):
        approved = self.digest()
        self.deny(diff={"src/renamed.py": "v2"}, digest=approved)

    def test_new_checkpoint_requires_fresh_review(self):
        current = self.mutate(checkpoint=4)
        self.deny(current=current, digest=self.digest())

    def test_missing_or_malformed_review_digest_fails_closed(self):
        for digest in ("", "yes", "0" * 63, True, None):
            if digest is None:
                digest = ""
            self.deny(digest=digest)

    def test_diff_paths_cannot_escape_repo_scope(self):
        for path in ("../secret", "/abs", "a//b", "a/./b", "a/../b", "C:/secret", "a\\b", ""):
            with self.assertRaises(PublicationDenied):
                publication_digest(authority=self.a, diff={path: "x"})

    def test_malformed_authority_fails_closed(self):
        for current in (self.mutate(chat_id=""), self.mutate(repo_scope=" "),
                        self.mutate(state_epoch=True), self.mutate(state_epoch=-1),
                        self.mutate(checkpoint=True), self.mutate(checkpoint=-1)):
            self.deny(current=current)


if __name__ == "__main__":
    unittest.main()
