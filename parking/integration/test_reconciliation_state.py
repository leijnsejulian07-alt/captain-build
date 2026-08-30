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

    def test_verified_requires_passing_checks(self):
        with self.assertRaises(ValueError):
            transition(self.empty, "scoped-jobs", "verified", {"unit": "failed"})

    def test_terminal_integrated_cannot_reopen(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed)
        state = transition(state, "scoped-jobs", "integrated", self.passed)
        with self.assertRaises(ValueError):
            transition(state, "scoped-jobs", "verified", self.passed)

    def test_rejected_is_terminal(self):
        state = transition(self.empty, "scoped-jobs", "rejected")
        with self.assertRaises(ValueError):
            transition(state, "scoped-jobs", "verified", self.passed)

    def test_malformed_state_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_state({"schema_version": 1, "components": {"x": {"state": "magic"}}})


if __name__ == "__main__":
    unittest.main()
