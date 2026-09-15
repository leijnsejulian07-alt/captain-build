from __future__ import annotations

import unittest

from model_route_failure_policy import (
    RouteFailurePolicyError,
    clear_route_failure_after_success,
    parse_failure_state,
    record_route_failure,
    route_failure_reason,
    validate_failure_states,
)


class ModelRouteFailurePolicyTests(unittest.TestCase):
    def test_transient_failures_back_off_exponentially_with_cap(self):
        first = record_route_failure(
            provider_id="local",
            model_id="m",
            failure_kind="transient",
            observed_at_ms=1_000,
        )
        self.assertEqual(first["retry_not_before_ms"], 16_000)
        previous = first
        observed = 20_000
        for _ in range(8):
            current = record_route_failure(
                provider_id="local",
                model_id="m",
                failure_kind="transient",
                observed_at_ms=observed,
                previous_state=previous,
            )
            previous = current
            observed += 400_000
        self.assertLessEqual(previous["retry_not_before_ms"] - previous["observed_at_ms"], 300_000)
        self.assertEqual(previous["disposition"], "cooldown")

    def test_rate_limit_honors_bounded_retry_after(self):
        state = record_route_failure(
            provider_id="free",
            model_id="m",
            failure_kind="rate_limited",
            observed_at_ms=10_000,
            retry_after_ms=120_000,
        )
        self.assertEqual(state["retry_not_before_ms"], 130_000)
        self.assertEqual(route_failure_reason(state, now_ms=129_999), "provider_cooldown")
        self.assertIsNone(route_failure_reason(state, now_ms=130_000))
        with self.assertRaises(RouteFailurePolicyError):
            record_route_failure(
                provider_id="free",
                model_id="m",
                failure_kind="rate_limited",
                observed_at_ms=20_000,
                retry_after_ms=3_600_001,
            )

    def test_auth_setup_permission_and_deprecation_block_without_auto_retry(self):
        for kind in ("auth_invalid", "permission_denied", "setup_required", "provider_deprecated"):
            state = record_route_failure(
                provider_id="p",
                model_id="m",
                failure_kind=kind,
                observed_at_ms=100,
            )
            self.assertEqual(state["disposition"], "blocked")
            self.assertIsNone(state["retry_not_before_ms"])
            self.assertEqual(route_failure_reason(state, now_ms=10_000_000), "provider_blocked")

    def test_success_clear_requires_exact_route_and_newer_observation(self):
        state = record_route_failure(
            provider_id="p",
            model_id="m",
            failure_kind="auth_invalid",
            observed_at_ms=1_000,
        )
        self.assertIsNone(clear_route_failure_after_success(
            state,
            provider_id="p",
            model_id="m",
            observed_at_ms=1_001,
        ))
        with self.assertRaises(RouteFailurePolicyError):
            clear_route_failure_after_success(state, provider_id="other", model_id="m", observed_at_ms=2_000)
        with self.assertRaises(RouteFailurePolicyError):
            clear_route_failure_after_success(state, provider_id="p", model_id="m", observed_at_ms=1_000)

    def test_previous_state_must_match_route_and_time_must_move_forward(self):
        state = record_route_failure(
            provider_id="p",
            model_id="m",
            failure_kind="transient",
            observed_at_ms=1_000,
        )
        with self.assertRaises(RouteFailurePolicyError):
            record_route_failure(
                provider_id="other",
                model_id="m",
                failure_kind="transient",
                observed_at_ms=2_000,
                previous_state=state,
            )
        with self.assertRaises(RouteFailurePolicyError):
            record_route_failure(
                provider_id="p",
                model_id="m",
                failure_kind="transient",
                observed_at_ms=1_000,
                previous_state=state,
            )

    def test_failure_kind_change_resets_streak(self):
        transient = record_route_failure(
            provider_id="p",
            model_id="m",
            failure_kind="transient",
            observed_at_ms=1_000,
        )
        limited = record_route_failure(
            provider_id="p",
            model_id="m",
            failure_kind="rate_limited",
            observed_at_ms=2_000,
            previous_state=transient,
        )
        self.assertEqual(limited["consecutive_failures"], 1)

    def test_schema_is_strict_and_secret_shaped_fields_are_rejected(self):
        state = record_route_failure(
            provider_id="p",
            model_id="m",
            failure_kind="transient",
            observed_at_ms=1_000,
        )
        bad = dict(state)
        bad["provider_error_body"] = "secret"
        with self.assertRaises(RouteFailurePolicyError):
            parse_failure_state(bad)
        with self.assertRaises(RouteFailurePolicyError):
            record_route_failure(
                provider_id="p",
                model_id="m",
                failure_kind="mystery",
                observed_at_ms=2_000,
            )

    def test_duplicate_failure_states_fail_closed(self):
        state = record_route_failure(
            provider_id="p",
            model_id="m",
            failure_kind="transient",
            observed_at_ms=1_000,
        )
        with self.assertRaises(RouteFailurePolicyError):
            validate_failure_states([state, state])


if __name__ == "__main__":
    unittest.main()
