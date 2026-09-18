import copy
import unittest

from parking.integration.reconciliation_rollback_guard import (
    advance_guard,
    issue_guard,
    validate_loaded,
)

SCOPE_A = "a" * 64
SCOPE_B = "b" * 64


class ReconciliationRollbackGuardTests(unittest.TestCase):
    def setUp(self):
        self.envelope = {"schema_version": 1, "scope_digest": SCOPE_A, "state": {"step": 1}}
        self.guard = issue_guard(self.envelope, scope_digest=SCOPE_A, generation=7)

    def test_current_generation_loads(self):
        validate_loaded(self.envelope, self.guard, expected_scope_digest=SCOPE_A, minimum_generation=7)

    def test_older_generation_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_loaded(self.envelope, self.guard, expected_scope_digest=SCOPE_A, minimum_generation=8)

    def test_cross_scope_replay_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_loaded(self.envelope, self.guard, expected_scope_digest=SCOPE_B, minimum_generation=7)

    def test_envelope_tamper_fails_closed(self):
        changed = copy.deepcopy(self.envelope)
        changed["state"]["step"] = 2
        with self.assertRaises(ValueError):
            validate_loaded(changed, self.guard, expected_scope_digest=SCOPE_A, minimum_generation=7)

    def test_unknown_guard_field_fails_closed(self):
        changed = dict(self.guard, extra=True)
        with self.assertRaises(ValueError):
            validate_loaded(self.envelope, changed, expected_scope_digest=SCOPE_A, minimum_generation=7)

    def test_generation_must_advance_exactly_once(self):
        with self.assertRaises(ValueError):
            advance_guard(self.guard, self.envelope, expected_scope_digest=SCOPE_A, next_generation=9)

    def test_valid_transition_rotates_digest_and_generation(self):
        changed = copy.deepcopy(self.envelope)
        changed["state"]["step"] = 2
        next_guard = advance_guard(self.guard, changed, expected_scope_digest=SCOPE_A, next_generation=8)
        self.assertEqual(next_guard["generation"], 8)
        self.assertNotEqual(next_guard["envelope_digest"], self.guard["envelope_digest"])

    def test_boolean_generation_is_rejected(self):
        with self.assertRaises(ValueError):
            issue_guard(self.envelope, scope_digest=SCOPE_A, generation=True)


if __name__ == "__main__":
    unittest.main()
