import unittest
from parking.builder_result_acceptance import BuilderOwner, accept_builder_result, rejection_reason

def owner(**changes):
    base=dict(chat_id="c1", project_id="p1", repo_scope="repo/a", epoch=7, builder_session_id="b1")
    base.update(changes)
    return BuilderOwner(**base)

class BuilderResultAcceptanceTests(unittest.TestCase):
    def test_exact_owner_is_accepted(self):
        self.assertTrue(accept_builder_result(owner(), owner()))

    def test_each_isolation_wall_fails_closed(self):
        for field, value in [("chat_id","c2"),("project_id","p2"),("repo_scope","repo/b"),("epoch",8),("builder_session_id","b2")]:
            with self.subTest(field=field):
                self.assertFalse(accept_builder_result(owner(), owner(**{field:value})))

    def test_stale_epoch_and_session_are_classified_safely(self):
        self.assertEqual(rejection_reason(owner(), owner(epoch=6)), "stale_epoch")
        self.assertEqual(rejection_reason(owner(), owner(builder_session_id="old")), "stale_builder_session")

    def test_malformed_project_scope_is_rejected(self):
        self.assertFalse(accept_builder_result(owner(), owner(repo_scope="")))
        self.assertEqual(rejection_reason(owner(), owner(repo_scope="")), "invalid_scope")

    def test_normal_non_project_chat_still_works(self):
        x=owner(project_id="", repo_scope="")
        self.assertTrue(accept_builder_result(x, x))

    def test_project_nonproject_crossing_is_rejected(self):
        nonproject=owner(project_id="", repo_scope="")
        self.assertFalse(accept_builder_result(owner(), nonproject))
        self.assertFalse(accept_builder_result(nonproject, owner()))

    def test_invalid_owner_is_rejected_without_echoing_sensitive_values(self):
        actual=owner(chat_id="")
        reason=rejection_reason(owner(), actual)
        self.assertEqual(reason, "invalid_owner")
        for sensitive in ("c1","p1","repo/a","b1"):
            self.assertNotIn(sensitive, reason)

if __name__ == "__main__":
    unittest.main()
