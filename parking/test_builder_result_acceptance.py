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

    def test_hostile_owner_shapes_fail_closed(self):
        bad = [
            owner(epoch=True), owner(epoch=-1), owner(epoch="7"),
            owner(chat_id=123), owner(chat_id="   "),
            owner(builder_session_id=None), owner(builder_session_id="   "),
            owner(project_id="   ", repo_scope="repo/a"),
            owner(project_id="p1", repo_scope="   "),
        ]
        for actual in bad:
            with self.subTest(actual=repr(actual)):
                self.assertFalse(accept_builder_result(owner(), actual))
                self.assertEqual(rejection_reason(owner(), actual), "invalid_owner")

    def test_hostile_expected_owner_is_classified_separately(self):
        for expected in (owner(epoch=True), owner(epoch=-1), owner(chat_id="   ")):
            with self.subTest(expected=repr(expected)):
                self.assertFalse(accept_builder_result(expected, owner()))
                self.assertEqual(rejection_reason(expected, owner()), "invalid_expected_owner")

if __name__ == "__main__":
    unittest.main()
