import unittest

from acceptance_gate import PromotionBlocked, PromotionCandidate, can_promote, public_gate_state

A = "a" * 40
B = "b" * 40


def candidate(**overrides):
    data = dict(candidate_id="builder-artifacts", source_sha=A, expected_local_base_sha=B, dependencies=("preview-sessions",))
    data.update(overrides)
    return PromotionCandidate(**data)


def green():
    return {
        "unit": "pass",
        "doctor": "pass",
        "router": "pass",
        "project_isolation": "pass",
        "repo_isolation": "pass",
    }


class AcceptanceGateTests(unittest.TestCase):
    def test_happy_path(self):
        self.assertTrue(can_promote(candidate(), actual_local_base_sha=B, checks=green(), integrated_dependencies=["preview-sessions"]))

    def test_stale_local_base_fails_closed(self):
        with self.assertRaises(PromotionBlocked):
            can_promote(candidate(), actual_local_base_sha=A, checks=green(), integrated_dependencies=["preview-sessions"])

    def test_missing_check_fails_closed(self):
        checks = green(); checks.pop("doctor")
        with self.assertRaises(PromotionBlocked):
            can_promote(candidate(), actual_local_base_sha=B, checks=checks, integrated_dependencies=["preview-sessions"])

    def test_failed_or_blocked_check_fails_closed(self):
        for status in ("fail", "blocked", "not_run"):
            checks = green(); checks["router"] = status
            with self.assertRaises(PromotionBlocked):
                can_promote(candidate(), actual_local_base_sha=B, checks=checks, integrated_dependencies=["preview-sessions"])

    def test_unknown_check_cannot_bypass_policy(self):
        checks = green(); checks["magic_override"] = "pass"
        with self.assertRaises(PromotionBlocked):
            can_promote(candidate(), actual_local_base_sha=B, checks=checks, integrated_dependencies=["preview-sessions"])

    def test_dependency_must_be_integrated(self):
        with self.assertRaises(PromotionBlocked):
            can_promote(candidate(), actual_local_base_sha=B, checks=green(), integrated_dependencies=[])

    def test_duplicate_self_or_pathlike_dependencies_rejected(self):
        bad = (("builder-artifacts",), ("../escape",), ("preview-sessions", "preview-sessions"))
        for deps in bad:
            with self.assertRaises(PromotionBlocked):
                public_gate_state(candidate(dependencies=deps))

    def test_invalid_sha_rejected(self):
        for value in ("main", "ABC", "a" * 39, "g" * 40):
            with self.assertRaises(PromotionBlocked):
                public_gate_state(candidate(source_sha=value))

    def test_public_state_contains_no_runtime_paths_or_secrets(self):
        state = public_gate_state(candidate())
        flat = repr(state).lower()
        for forbidden in ("c:\\", "/users/", "token", "api_key", "password", "authorization"):
            self.assertNotIn(forbidden, flat)


if __name__ == "__main__":
    unittest.main()
