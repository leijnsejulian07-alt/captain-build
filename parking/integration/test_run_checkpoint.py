import unittest

from run_checkpoint import begin_run, finish_run, validate_checkpoint


class RunCheckpointTests(unittest.TestCase):
    def test_first_run_has_no_gap(self):
        state, info = begin_run(None, "2026-08-31T00:00:00Z")
        self.assertEqual(state["last_status"], "running")
        self.assertFalse(info["gap_detected"])
        self.assertFalse(info["resume_from_checkpoint"])
        self.assertFalse(info["interrupted_prior_run"])

    def test_normal_hourly_resume_has_no_gap(self):
        prior = {"schema_version": 1, "last_started_at": "2026-08-31T00:00:00Z", "last_status": "completed", "last_completed_at": "2026-08-31T00:05:00Z"}
        _, info = begin_run(prior, "2026-08-31T01:05:00Z")
        self.assertTrue(info["resume_from_checkpoint"])
        self.assertFalse(info["gap_detected"])
        self.assertFalse(info["interrupted_prior_run"])

    def test_missed_interval_is_reported(self):
        prior = {"schema_version": 1, "last_started_at": "2026-08-31T00:00:00Z", "last_status": "partial", "last_completed_at": "2026-08-31T00:10:00Z"}
        _, info = begin_run(prior, "2026-08-31T03:00:00Z")
        self.assertTrue(info["gap_detected"])
        self.assertEqual(info["gap_seconds"], 10800)

    def test_interrupted_running_checkpoint_is_reported(self):
        prior = {"schema_version": 1, "last_started_at": "2026-08-31T00:00:00Z", "last_status": "running"}
        _, info = begin_run(prior, "2026-08-31T01:00:00Z")
        self.assertTrue(info["resume_from_checkpoint"])
        self.assertTrue(info["interrupted_prior_run"])

    def test_timestamp_must_be_monotonic(self):
        prior = {"schema_version": 1, "last_started_at": "2026-08-31T01:00:00Z", "last_status": "blocked_transient", "last_completed_at": "2026-08-31T01:01:00Z"}
        with self.assertRaises(ValueError):
            begin_run(prior, "2026-08-31T00:59:59Z")

    def test_unknown_fields_fail_closed(self):
        with self.assertRaises(ValueError):
            validate_checkpoint({"schema_version": 1, "token": "secret"})

    def test_old_schema_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_checkpoint({"schema_version": 0})

    def test_terminal_status_requires_completion(self):
        with self.assertRaises(ValueError):
            validate_checkpoint({"schema_version": 1, "last_started_at": "2026-08-31T00:00:00Z", "last_status": "completed"})

    def test_running_status_rejects_completion(self):
        with self.assertRaises(ValueError):
            validate_checkpoint({"schema_version": 1, "last_started_at": "2026-08-31T00:00:00Z", "last_completed_at": "2026-08-31T00:01:00Z", "last_status": "running"})

    def test_timestamps_without_status_fail_closed(self):
        with self.assertRaises(ValueError):
            validate_checkpoint({"schema_version": 1, "last_started_at": "2026-08-31T00:00:00Z"})

    def test_finish_requires_running_state(self):
        with self.assertRaises(ValueError):
            finish_run({"schema_version": 1}, "2026-08-31T00:01:00Z", "completed")

    def test_finish_rejects_time_reversal(self):
        state, _ = begin_run(None, "2026-08-31T00:10:00Z")
        with self.assertRaises(ValueError):
            finish_run(state, "2026-08-31T00:09:59Z", "completed")

    def test_finish_persists_only_safe_fields(self):
        state, _ = begin_run(None, "2026-08-31T00:00:00Z")
        result = finish_run(state, "2026-08-31T00:02:00Z", "partial")
        self.assertEqual(set(result), {"schema_version", "last_started_at", "last_completed_at", "last_status"})
        self.assertEqual(result["last_status"], "partial")


if __name__ == "__main__":
    unittest.main()
