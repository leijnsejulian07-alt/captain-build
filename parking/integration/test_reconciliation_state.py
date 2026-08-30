import unittest

from reconciliation_state import transition, validate_state


class ReconciliationStateTests(unittest.TestCase):
    def setUp(self):
        self.empty = {"schema_version": 1, "components": {}}
        self.passed = {"unit": "passed", "doctor": "passed", "router": "passed", "project_isolation": "passed", "repo_isolation": "passed"}

    def test_pending_to_verified_to_integrated(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed)
        state = transition(state, "scoped-jobs", "integrated", self.passed)
        self.assertEqual(state["components"]["scoped-jobs"]["state"], "integrated")

    def test_verified_requires_exact_passing_checks(self):
        with self.assertRaises(ValueError):
            transition(self.empty, "scoped-jobs", "verified", {"unit": "passed"})
        extra = dict(self.passed, surprise="passed")
        with self.assertRaises(ValueError):
            transition(self.empty, "scoped-jobs", "verified", extra)
        failed = dict(self.passed, router="failed")
        with self.assertRaises(ValueError):
            transition(self.empty, "scoped-jobs", "verified", failed)

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

    def test_unknown_fields_fail_closed(self):
        with self.assertRaises(ValueError):
            validate_state({"schema_version": 1, "components": {}, "token": "secret"})
        with self.assertRaises(ValueError):
            validate_state({"schema_version": 1, "components": {"x": {"state": "pending", "note": "raw"}}})

    def test_malformed_state_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_state({"schema_version": 1, "components": {"x": {"state": "magic"}}})


if __name__ == "__main__":
    unittest.main()
