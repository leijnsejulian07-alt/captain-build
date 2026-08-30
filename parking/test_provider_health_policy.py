import unittest

from provider_health_policy import PolicyError, ProviderState, choose_provider, cooldown_for_failure, public_route_metadata


def p(name="local", **kw):
    base = dict(provider_id=name, state="healthy", success_rate=0.95, latency_ms=100, cooldown_until=0, is_local=True, is_free=False, paid=False)
    base.update(kw)
    return ProviderState(**base)


class ProviderHealthPolicyTests(unittest.TestCase):
    def test_local_only_rejects_cloud(self):
        cloud = p("cloud", is_local=False, is_free=True)
        with self.assertRaises(PolicyError):
            choose_provider([cloud], "local-only", now=100)

    def test_free_cloud_never_silently_uses_paid(self):
        paid = p("paid", is_local=False, paid=True, is_free=False, paid_approved=True)
        free = p("free", is_local=False, is_free=True, paid=False, success_rate=0.60)
        self.assertEqual(choose_provider([paid, free], "free-cloud", now=100).provider_id, "free")

    def test_approved_paid_requires_explicit_approval(self):
        paid = p("paid", is_local=False, paid=True, is_free=False, paid_approved=False)
        with self.assertRaises(PolicyError):
            choose_provider([paid], "approved-paid", now=100)

    def test_cooldown_blocks_otherwise_healthy_provider(self):
        cooling = p("cooling", cooldown_until=101)
        with self.assertRaises(PolicyError):
            choose_provider([cooling], "local-only", now=100)

    def test_auth_failed_is_never_routed(self):
        bad = p("bad", state="auth_failed")
        with self.assertRaises(PolicyError):
            choose_provider([bad], "local-only", now=100)

    def test_health_score_prefers_reliable_over_fast_but_degraded(self):
        reliable = p("reliable", success_rate=0.96, latency_ms=500)
        degraded = p("degraded", state="degraded", success_rate=0.99, latency_ms=20)
        self.assertEqual(choose_provider([degraded, reliable], "local-only", now=100).provider_id, "reliable")

    def test_backoff_is_bounded(self):
        self.assertEqual(cooldown_for_failure("rate_limit", 1), 60)
        self.assertEqual(cooldown_for_failure("rate_limit", 8), 3600)

    def test_public_metadata_contains_no_secret_fields(self):
        meta = public_route_metadata(p(), "local-only")
        blob = repr(meta).lower()
        for forbidden in ("token", "secret", "authorization", "api_key", "cookie"):
            self.assertNotIn(forbidden, blob)

    def test_path_like_provider_ids_fail_closed(self):
        for bad in ("../x", "a/b", "a\\b"):
            with self.assertRaises(PolicyError):
                p(bad)

    def test_invalid_paid_free_combination_rejected(self):
        with self.assertRaises(PolicyError):
            p("bad", paid=True, is_free=True)


if __name__ == "__main__":
    unittest.main()
