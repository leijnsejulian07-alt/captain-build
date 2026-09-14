from __future__ import annotations

import unittest

from model_route_failure_policy import record_route_failure
from model_route_policy import RoutePolicyError, choose_route


def candidate(provider_id, model_id, *, cost_class="free", health="healthy", enabled=True, ready=True, capabilities=("chat",), priority=100):
    return {
        "provider_id": provider_id,
        "model_id": model_id,
        "cost_class": cost_class,
        "health": health,
        "enabled": enabled,
        "ready": ready,
        "capabilities": list(capabilities),
        "priority": priority,
    }


class ModelRoutePolicyTests(unittest.TestCase):
    def test_prefers_healthy_local_then_free_without_paid_activation(self):
        result = choose_route([
            candidate("cloud-free", "m1", cost_class="free", priority=1),
            candidate("local", "m2", cost_class="local", priority=50),
            candidate("paid", "m3", cost_class="paid", priority=0),
        ], task="chat")
        self.assertEqual(result["selected"]["provider_id"], "local")
        self.assertFalse(result["paid_authorized"])
        self.assertIn("paid_not_authorized", {item["reason"] for item in result["rejected"]})
        self.assertEqual(result["secret_fields"], [])

    def test_paid_route_requires_explicit_authorization(self):
        only_paid = [candidate("paid", "m", cost_class="paid")]
        blocked = choose_route(only_paid, task="chat")
        self.assertIsNone(blocked["selected"])
        allowed = choose_route(only_paid, task="chat", allow_paid=True)
        self.assertEqual(allowed["selected"]["provider_id"], "paid")

    def test_unready_disabled_unavailable_and_missing_capability_are_rejected(self):
        result = choose_route([
            candidate("a", "m", enabled=False),
            candidate("b", "m", ready=False),
            candidate("c", "m", health="unavailable"),
            candidate("d", "m", capabilities=("coding",)),
        ], task="research")
        self.assertIsNone(result["selected"])
        self.assertEqual(
            {item["reason"] for item in result["rejected"]},
            {"disabled", "not_ready", "unavailable", "missing_capability"},
        )

    def test_healthy_beats_degraded_even_when_degraded_is_local(self):
        result = choose_route([
            candidate("local", "m", cost_class="local", health="degraded", priority=0),
            candidate("free", "m", cost_class="free", health="healthy", priority=999),
        ], task="chat")
        self.assertEqual(result["selected"]["provider_id"], "free")

    def test_excluded_route_enables_deterministic_fallback(self):
        candidates = [
            candidate("local", "a", cost_class="local", priority=0),
            candidate("free", "b", cost_class="free", priority=0),
        ]
        first = choose_route(candidates, task="chat")
        self.assertEqual(first["selected"]["provider_id"], "local")
        second = choose_route(candidates, task="chat", excluded_routes=(("local", "a"),))
        self.assertEqual(second["selected"]["provider_id"], "free")
        self.assertIn("already_attempted", {item["reason"] for item in second["rejected"]})

    def test_active_cooldown_routes_to_next_free_candidate(self):
        cooldown = record_route_failure(
            provider_id="local",
            model_id="a",
            failure_kind="transient",
            observed_at_ms=1_000,
        )
        result = choose_route([
            candidate("local", "a", cost_class="local", priority=0),
            candidate("free", "b", cost_class="free", priority=0),
        ], task="chat", failure_states=(cooldown,), now_ms=2_000)
        self.assertEqual(result["selected"]["provider_id"], "free")
        self.assertIn("provider_cooldown", {item["reason"] for item in result["rejected"]})

    def test_expired_cooldown_restores_route_eligibility(self):
        cooldown = record_route_failure(
            provider_id="local",
            model_id="a",
            failure_kind="transient",
            observed_at_ms=1_000,
        )
        result = choose_route([
            candidate("local", "a", cost_class="local", priority=0),
            candidate("free", "b", cost_class="free", priority=0),
        ], task="chat", failure_states=(cooldown,), now_ms=cooldown["retry_not_before_ms"])
        self.assertEqual(result["selected"]["provider_id"], "local")

    def test_blocked_route_never_auto_retries(self):
        blocked = record_route_failure(
            provider_id="local",
            model_id="a",
            failure_kind="auth_invalid",
            observed_at_ms=1_000,
        )
        result = choose_route([
            candidate("local", "a", cost_class="local"),
            candidate("free", "b", cost_class="free"),
        ], task="chat", failure_states=(blocked,), now_ms=9_999_999)
        self.assertEqual(result["selected"]["provider_id"], "free")
        self.assertIn("provider_blocked", {item["reason"] for item in result["rejected"]})

    def test_cooldown_never_unlocks_paid_fallback_without_authorization(self):
        cooldown = record_route_failure(
            provider_id="free",
            model_id="a",
            failure_kind="rate_limited",
            observed_at_ms=1_000,
        )
        result = choose_route([
            candidate("free", "a", cost_class="free"),
            candidate("paid", "b", cost_class="paid"),
        ], task="chat", failure_states=(cooldown,), now_ms=2_000)
        self.assertIsNone(result["selected"])
        self.assertEqual(
            {item["reason"] for item in result["rejected"]},
            {"provider_cooldown", "paid_not_authorized"},
        )

    def test_failure_state_requires_explicit_clock_and_is_route_scoped(self):
        state = record_route_failure(
            provider_id="other",
            model_id="m",
            failure_kind="transient",
            observed_at_ms=1_000,
        )
        with self.assertRaises(RoutePolicyError):
            choose_route([candidate("local", "m")], task="chat", failure_states=(state,))
        result = choose_route([candidate("local", "m")], task="chat", failure_states=(state,), now_ms=2_000)
        self.assertEqual(result["selected"]["provider_id"], "local")

    def test_duplicate_route_fails_closed(self):
        with self.assertRaises(RoutePolicyError):
            choose_route([candidate("x", "m"), candidate("x", "m")], task="chat")

    def test_unknown_fields_and_bad_task_fail_closed(self):
        bad = candidate("x", "m")
        bad["api_key"] = "do-not-accept-secret-shaped-fields"
        with self.assertRaises(RoutePolicyError):
            choose_route([bad], task="chat")
        with self.assertRaises(RoutePolicyError):
            choose_route([], task="unknown")

    def test_deterministic_tie_breaker(self):
        result = choose_route([
            candidate("z", "m", cost_class="free", priority=10),
            candidate("a", "m", cost_class="free", priority=10),
        ], task="chat")
        self.assertEqual(result["selected"]["provider_id"], "a")


if __name__ == "__main__":
    unittest.main()
