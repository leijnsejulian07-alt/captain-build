import unittest

from reconciliation_state import set_local_base, transition, validate_state


class ReconciliationStateTests(unittest.TestCase):
    def setUp(self):
        self.sha = "a" * 40
        self.other_sha = "b" * 40
        self.empty = {"schema_version": 4, "local_base_sha": self.sha, "components": {}}
        self.passed = {"unit": "passed", "doctor": "passed", "router": "passed", "project_isolation": "passed", "repo_isolation": "passed"}
        self.t0 = "2026-08-31T12:00:00Z"
        self.t20 = "2026-08-31T12:20:00Z"
        self.t31 = "2026-08-31T12:31:00Z"

    def test_pending_to_verified_to_integrated(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed, now=self.t0)
        self.assertEqual(len(state["components"]["scoped-jobs"]["evidence_digest"]), 64)
        self.assertEqual(state["components"]["scoped-jobs"]["verified_at"], self.t0)
        state = transition(state, "scoped-jobs", "integrated", self.passed, now=self.t20)
        self.assertEqual(state["components"]["scoped-jobs"]["state"], "integrated")
        self.assertEqual(state["components"]["scoped-jobs"]["verified_base_sha"], self.sha)
        self.assertEqual(state["components"]["scoped-jobs"]["verified_at"], self.t0)

    def test_verified_evidence_expires_before_promotion(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed, now=self.t0)
        with self.assertRaises(ValueError):
            transition(state, "scoped-jobs", "integrated", self.passed, now=self.t31)
        with self.assertRaises(ValueError):
            validate_state(state, now=self.t31)

    def test_integrated_audit_evidence_does_not_expire(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed, now=self.t0)
        state = transition(state, "scoped-jobs", "integrated", self.passed, now=self.t20)
        validate_state(state, now="2027-08-31T12:20:00Z")

    def test_future_verified_timestamp_fails_closed(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed, now=self.t0)
        with self.assertRaises(ValueError):
            validate_state(state, now="2026-08-31T11:58:00Z")

    def test_tampered_verified_timestamp_fails_closed(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed, now=self.t0)
        state["components"]["scoped-jobs"]["verified_at"] = "2026-08-31T12:01:00Z"
        with self.assertRaises(ValueError):
            validate_state(state, now=self.t20)

    def test_tampered_evidence_digest_fails_closed(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed, now=self.t0)
        state["components"]["scoped-jobs"]["evidence_digest"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_state(state, now=self.t20)

    def test_tampered_checks_fail_closed_even_if_still_passing(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed, now=self.t0)
        state["components"]["scoped-jobs"]["checks"] = dict(self.passed)
        state["components"]["scoped-jobs"]["checks"]["unit"] = "failed"
        with self.assertRaises(ValueError):
            validate_state(state, now=self.t20)

    def test_verified_requires_exact_passing_checks(self):
        with self.assertRaises(ValueError):
            transition(self.empty, "scoped-jobs", "verified", {"unit": "passed"}, now=self.t0)
        with self.assertRaises(ValueError):
            transition(self.empty, "scoped-jobs", "verified", dict(self.passed, surprise="passed"), now=self.t0)
        with self.assertRaises(ValueError):
            transition(self.empty, "scoped-jobs", "verified", dict(self.passed, router="failed"), now=self.t0)

    def test_verification_requires_local_base(self):
        no_base = {"schema_version": 4, "local_base_sha": None, "components": {}}
        with self.assertRaises(ValueError):
            transition(no_base, "scoped-jobs", "verified", self.passed, now=self.t0)

    def test_stale_verified_base_fails_closed(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed, now=self.t0)
        state["local_base_sha"] = self.other_sha
        with self.assertRaises(ValueError):
            validate_state(state, now=self.t20)

    def test_local_base_can_only_change_before_verification(self):
        state = set_local_base({"schema_version": 4, "local_base_sha": None, "components": {}}, self.sha)
        self.assertEqual(state["local_base_sha"], self.sha)
        state = transition(state, "scoped-jobs", "verified", self.passed, now=self.t0)
        with self.assertRaises(ValueError):
            set_local_base(state, self.other_sha)

    def test_terminal_integrated_cannot_reopen(self):
        state = transition(self.empty, "scoped-jobs", "verified", self.passed, now=self.t0)
        state = transition(state, "scoped-jobs", "integrated", self.passed, now=self.t20)
        with self.assertRaises(ValueError):
            transition(state, "scoped-jobs", "verified", self.passed, now=self.t20)

    def test_rejected_is_terminal_and_cannot_carry_checks(self):
        state = transition(self.empty, "scoped-jobs", "rejected", now=self.t0)
        with self.assertRaises(ValueError):
            transition(state, "scoped-jobs", "verified", self.passed, now=self.t0)
        with self.assertRaises(ValueError):
            transition(self.empty, "other", "rejected", self.passed, now=self.t0)

    def test_path_like_component_ids_fail_closed(self):
        for component_id in ("../jobs", "jobs/x", "jobs\\x", "", "UPPER"):
            with self.assertRaises(ValueError):
                transition(self.empty, component_id, "rejected", now=self.t0)

    def test_unknown_fields_bad_sha_and_old_schema_fail_closed(self):
        with self.assertRaises(ValueError):
            validate_state({"schema_version": 4, "local_base_sha": self.sha, "components": {}, "token": "secret"}, now=self.t0)
        with self.assertRaises(ValueError):
            validate_state({"schema_version": 4, "local_base_sha": "main", "components": {}}, now=self.t0)
        with self.assertRaises(ValueError):
            validate_state({"schema_version": 3, "local_base_sha": self.sha, "components": {}}, now=self.t0)
        with self.assertRaises(ValueError):
            validate_state({"schema_version": 4, "local_base_sha": self.sha, "components": {"x": {"state": "pending", "note": "raw"}}}, now=self.t0)

    def test_malformed_state_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_state({"schema_version": 4, "local_base_sha": self.sha, "components": {"x": {"state": "magic"}}}, now=self.t0)


if __name__ == "__main__":
    unittest.main()
