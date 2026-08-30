import unittest

from reconciliation_state import set_local_base, transition, validate_state


class ReconciliationStateTests(unittest.TestCase):
    def setUp(self):
        self.sha = "a" * 40
        self.other_sha = "b" * 40
        self.empty = {"schema_version": 2, "local_base_sha": self.sha, "components": {}}
        self.passed = {"unit": "passed", "doctor": "passed", "router": "passed", "project_isolation": "passed", "repo_isolation": "passed"}

    def test_pending_to_verified_to_integrated(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed)
        state = transition(state, "scoped-jobs", "integrated", self.passed)
        self.assertEqual(state["components"]["scoped-jobs"]["state"], "integrated")
        self.assertEqual(state["components"]["scoped-jobs"]["verified_base_sha"], self.sha)

    def test_verified_requires_exact_passing_checks(self):
        with self.assertRaises(ValueError):
            transition(self.empty, "scoped-jobs", "verified", {"unit": "passed"})
        with self.assertRaises(ValueError):
            transition(self.empty, "scoped-jobs", "verified", dict(self.passed, surprise="passed"))
        with self.assertRaises(ValueError):
            transition(self.empty, "scoped-jobs", "verified", dict(self.passed, router="failed"))

    def test_verification_requires_local_base(self):
        no_base = {"schema_version": 2, "local_base_sha": None, "components": {}}
        with self.assertRaises(ValueError):
            transition(no_base, "scoped-jobs", "verified", self.passed)

    def test_stale_verified_base_fails_closed(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed)
        state["local_base_sha"] = self.other_sha
        with self.assertRaises(ValueError):
            validate_state(state)

    def test_local_base_can_only_change_before_verification(self):
        state = set_local_base({"schema_version": 2, "local_base_sha": None, "components": {}}, self.sha)
        self.assertEqual(state["local_base_sha"], self.sha)
        state = transition(state, "scoped-jobs", "verified", self.passed)
        with self.assertRaises(ValueError):
            set_local_base(state, self.other_sha)

    def test_terminal_integrated_cannot_reopen(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed)
        state = transition(state, "scoped-jobs", "integrated", self.passed)
        with self.assertRaises(ValueError):
            transition(state, "scoped-jobs", "verified", self.passed)

    def test_rejected_is_terminal_and_cannot_carry_checks(self):
        state = transition(self.empty, "scoped-jobs", "rejected")
        with self.assertRaises(ValueError):
            transition(state, "scoped-jobs", "verified", self.passed)
        with self.assertRaises(ValueError):
            transition(self.empty, "other", "rejected", self.passed)

    def test_path_like_component_ids_fail_closed(self):
        for component_id in ("../jobs", "jobs/x", "jobs\\x", "", "UPPER"):
            with self.assertRaises(ValueError):
                transition(self.empty, component_id, "rejected")

    def test_unknown_fields_and_bad_sha_fail_closed(self):
        with self.assertRaises(ValueError):
            validate_state({"schema_version": 2, "local_base_sha": self.sha, "components": {}, "token": "secret"})
        with self.assertRaises(ValueError):
            validate_state({"schema_version": 2, "local_base_sha": "main", "components": {}})
        with self.assertRaises(ValueError):
            validate_state({"schema_version": 2, "local_base_sha": self.sha, "components": {"x": {"state": "pending", "note": "raw"}}})

    def test_malformed_state_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_state({"schema_version": 2, "local_base_sha": self.sha, "components": {"x": {"state": "magic"}}})


if __name__ == "__main__":
    unittest.main()
