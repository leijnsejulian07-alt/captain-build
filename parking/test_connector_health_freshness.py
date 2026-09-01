import unittest

from connector_health_freshness import (
    ConnectorHealthEvidence,
    ConnectorHealthWatermark,
    project_connector_health,
)


def base(**overrides):
    state = {
        "id": "github",
        "kind": "connector",
        "auth_method": "oauth",
        "setup_version": 2,
        "health": "ok",
        "ready": True,
        "issues": [],
        "next_action": None,
    }
    state.update(overrides)
    return state


def evidence(**overrides):
    data = dict(plugin_id="github", checked_at=1000, health="ok", auth_method="oauth", setup_version=2)
    data.update(overrides)
    return ConnectorHealthEvidence(**data)


def watermark(**overrides):
    data = dict(plugin_id="github", auth_method="oauth", setup_version=2, checked_at=1000)
    data.update(overrides)
    return ConnectorHealthWatermark(**data)


class ConnectorHealthFreshnessTests(unittest.TestCase):
    def test_fresh_matching_health_preserves_ready(self):
        out = project_connector_health(base(), evidence(), now=1100)
        self.assertTrue(out["ready"])
        self.assertTrue(out["health_evidence_fresh"])
        self.assertEqual(out["issues"], [])

    def test_missing_health_evidence_fails_closed(self):
        out = project_connector_health(base(), None, now=1100)
        self.assertFalse(out["ready"])
        self.assertIn("health-check-missing", out["issues"])
        self.assertEqual(out["next_action"], "test-connection")

    def test_stale_health_evidence_fails_closed(self):
        out = project_connector_health(base(), evidence(checked_at=1000), now=1000 + 86401)
        self.assertFalse(out["ready"])
        self.assertIn("health-check-stale", out["issues"])

    def test_auth_migration_invalidates_old_health_evidence(self):
        out = project_connector_health(base(auth_method="api-key"), evidence(auth_method="oauth"), now=1100)
        self.assertFalse(out["ready"])
        self.assertIn("health-check-auth-method-mismatch", out["issues"])

    def test_setup_migration_invalidates_old_health_evidence(self):
        out = project_connector_health(base(setup_version=3), evidence(setup_version=2), now=1100)
        self.assertFalse(out["ready"])
        self.assertIn("health-check-setup-version-mismatch", out["issues"])

    def test_future_timestamp_fails_closed(self):
        out = project_connector_health(base(), evidence(checked_at=1200), now=1100)
        self.assertFalse(out["ready"])
        self.assertIn("health-check-from-future", out["issues"])

    def test_unhealthy_fresh_evidence_cannot_claim_ready(self):
        out = project_connector_health(base(), evidence(health="auth-expired"), now=1100)
        self.assertFalse(out["ready"])
        self.assertIn("health-auth-expired", out["issues"])

    def test_health_projection_can_never_upgrade_not_ready(self):
        out = project_connector_health(
            base(ready=False, issues=["permission-approval-required"], next_action="review-permissions"),
            evidence(),
            now=1100,
        )
        self.assertFalse(out["ready"])
        self.assertEqual(out["next_action"], "review-permissions")

    def test_non_connector_state_is_unchanged(self):
        state = base(kind="skill")
        self.assertEqual(project_connector_health(state, None, now=1100), state)

    def test_mismatched_plugin_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            project_connector_health(base(), evidence(plugin_id="gitlab"), now=1100)

    def test_older_but_fresh_evidence_is_rejected_with_same_config_watermark(self):
        out = project_connector_health(base(), evidence(checked_at=1000), now=1100, watermark=watermark(checked_at=1050))
        self.assertFalse(out["ready"])
        self.assertIn("health-check-replayed", out["issues"])
        self.assertEqual(out["next_action"], "test-connection")

    def test_equal_timestamp_is_idempotent_only_with_same_config(self):
        out = project_connector_health(base(), evidence(checked_at=1000), now=1100, watermark=watermark(checked_at=1000))
        self.assertTrue(out["ready"])
        self.assertNotIn("health-check-replayed", out["issues"])

    def test_newer_evidence_advances_with_same_config(self):
        out = project_connector_health(base(), evidence(checked_at=1050), now=1100, watermark=watermark(checked_at=1000))
        self.assertTrue(out["ready"])
        self.assertEqual(out["health_evidence_checked_at"], 1050)

    def test_old_config_watermark_does_not_block_new_auth_config(self):
        out = project_connector_health(
            base(auth_method="api-key", setup_version=3),
            evidence(auth_method="api-key", setup_version=3, checked_at=900),
            now=1100,
            watermark=watermark(auth_method="oauth", setup_version=2, checked_at=1050),
        )
        self.assertTrue(out["ready"])
        self.assertNotIn("health-check-replayed", out["issues"])

    def test_old_evidence_after_migration_still_fails_closed(self):
        out = project_connector_health(
            base(auth_method="api-key", setup_version=3),
            evidence(auth_method="oauth", setup_version=2, checked_at=1100),
            now=1100,
            watermark=watermark(auth_method="oauth", setup_version=2, checked_at=1050),
        )
        self.assertFalse(out["ready"])
        self.assertIn("health-check-auth-method-mismatch", out["issues"])

    def test_cross_plugin_watermark_substitution_is_rejected(self):
        with self.assertRaises(ValueError):
            project_connector_health(base(), evidence(), now=1100, watermark=watermark(plugin_id="gitlab"))

    def test_equal_timestamp_from_old_config_does_not_gain_idempotence(self):
        out = project_connector_health(
            base(auth_method="api-key", setup_version=3),
            evidence(auth_method="api-key", setup_version=3, checked_at=1000),
            now=1100,
            watermark=watermark(auth_method="oauth", setup_version=2, checked_at=1000),
        )
        self.assertTrue(out["ready"])

    def test_invalid_watermark_fails_closed(self):
        for bad in (True, -1, 2**63):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                project_connector_health(base(), evidence(), now=1100, watermark=watermark(checked_at=bad))
        with self.assertRaises(ValueError):
            project_connector_health(base(), evidence(), now=1100, watermark=watermark(checked_at=1200))

    def test_invalid_bounds_fail_closed(self):
        for bad_now in (True, -1):
            with self.subTest(bad_now=bad_now), self.assertRaises(ValueError):
                project_connector_health(base(), evidence(), now=bad_now)
        for bad_age in (True, 0, 7 * 24 * 60 * 60 + 1):
            with self.subTest(bad_age=bad_age), self.assertRaises(ValueError):
                project_connector_health(base(), evidence(), now=1100, max_age_seconds=bad_age)


if __name__ == "__main__":
    unittest.main()
