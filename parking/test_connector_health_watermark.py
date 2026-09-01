import unittest

from connector_health_freshness import ConnectorHealthEvidence, ConnectorHealthWatermark
from connector_health_watermark import advance_health_watermark


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
    data = dict(plugin_id="github", auth_method="oauth", setup_version=2, checked_at=900)
    data.update(overrides)
    return ConnectorHealthWatermark(**data)


class ConnectorHealthWatermarkTests(unittest.TestCase):
    def test_fresh_success_advances_watermark(self):
        out = advance_health_watermark(base(), evidence(checked_at=1000), now=1100, previous=watermark())
        self.assertEqual(out, watermark(checked_at=1000))

    def test_replayed_evidence_cannot_advance(self):
        previous = watermark(checked_at=1050)
        out = advance_health_watermark(base(), evidence(checked_at=1000), now=1100, previous=previous)
        self.assertIs(out, previous)

    def test_unhealthy_evidence_cannot_advance(self):
        previous = watermark(checked_at=900)
        out = advance_health_watermark(base(), evidence(checked_at=1000, health="degraded"), now=1100, previous=previous)
        self.assertIs(out, previous)

    def test_auth_migration_accepts_only_matching_new_config(self):
        previous = watermark(auth_method="oauth", setup_version=2, checked_at=1050)
        out = advance_health_watermark(
            base(auth_method="api-key", setup_version=3),
            evidence(auth_method="api-key", setup_version=3, checked_at=1000),
            now=1100,
            previous=previous,
        )
        self.assertEqual(out, watermark(auth_method="api-key", setup_version=3, checked_at=1000))

    def test_base_not_ready_does_not_turn_ready_but_health_can_advance(self):
        previous = watermark(checked_at=900)
        out = advance_health_watermark(
            base(ready=False, issues=["permission-approval-required"], next_action="review-permissions"),
            evidence(checked_at=1000),
            now=1100,
            previous=previous,
        )
        self.assertEqual(out.checked_at, 1000)

    def test_non_connector_state_is_rejected(self):
        with self.assertRaises(ValueError):
            advance_health_watermark(base(kind="skill"), evidence(), now=1100)

    def test_plugin_substitution_is_rejected(self):
        with self.assertRaises(ValueError):
            advance_health_watermark(base(), evidence(plugin_id="gitlab"), now=1100, previous=watermark())

    def test_future_evidence_cannot_advance(self):
        previous = watermark(checked_at=900)
        out = advance_health_watermark(base(), evidence(checked_at=1200), now=1100, previous=previous)
        self.assertIs(out, previous)


if __name__ == "__main__":
    unittest.main()
