from datetime import datetime, timedelta, timezone
import unittest

from connector_settings_contract import (
    ContractError,
    apply_provider_compatibility,
    build_notice,
    evaluate_provider_compatibility,
    should_surface,
    validate_connector_state,
    validate_provider_expectation,
)


BASE = {
    "schema_version": 1,
    "connector_id": "github",
    "project_id": "project-a",
    "installed": True,
    "connected": True,
    "enabled": True,
    "ready": True,
    "auth_method": "oauth",
    "health": "healthy",
    "permissions_granted": ["read"],
    "permissions_required": ["read"],
    "issue_code": None,
}

EXPECTATION = {
    "schema_version": 1,
    "connector_id": "github",
    "auth_method": "oauth",
    "setup_version": "2026-09",
    "minimum_client_version": "1.4.0",
    "deprecated_auth_methods": ["api_key"],
}

OBSERVED = {
    "schema_version": 1,
    "connector_id": "github",
    "auth_method": "oauth",
    "setup_version": "2026-09",
    "client_version": "1.4.0",
}


class ConnectorSettingsContractTests(unittest.TestCase):
    def test_ready_state_passes(self):
        self.assertTrue(validate_connector_state(dict(BASE)))

    def test_ready_cannot_be_claimed_inconsistently(self):
        state = dict(BASE)
        state["ready"] = False
        with self.assertRaises(ContractError):
            validate_connector_state(state)

    def test_missing_required_permission_is_not_ready(self):
        state = dict(BASE)
        state["permissions_required"] = ["write"]
        state["ready"] = False
        self.assertTrue(validate_connector_state(state))

    def test_unhealthy_connector_requires_issue_code(self):
        state = dict(BASE)
        state.update(ready=False, health="expired_auth", issue_code=None)
        with self.assertRaises(ContractError):
            validate_connector_state(state)

    def test_notice_cannot_cross_project_scope(self):
        now = datetime.now(timezone.utc)
        state = dict(BASE)
        state.update(ready=False, health="expired_auth", issue_code="reauth")
        notice = build_notice(state, "settings://connectors/github", now)
        other = dict(state)
        other["project_id"] = "project-b"
        with self.assertRaises(ContractError):
            should_surface(notice, other, now)

    def test_temporarily_dismissed_notice_reappears(self):
        now = datetime.now(timezone.utc)
        state = dict(BASE)
        state.update(ready=False, health="setup_required", issue_code="setup")
        notice = build_notice(state, "settings://connectors/github", now, now + timedelta(hours=2))
        self.assertFalse(should_surface(notice, state, now + timedelta(hours=1)))
        self.assertTrue(should_surface(notice, state, now + timedelta(hours=3)))

    def test_resolved_notice_clears_automatically(self):
        now = datetime.now(timezone.utc)
        self.assertFalse(should_surface(None, dict(BASE), now))

    def test_notice_contract_contains_no_secret_payload(self):
        now = datetime.now(timezone.utc)
        state = dict(BASE)
        state.update(ready=False, health="invalid_auth", issue_code="reauth")
        notice = build_notice(state, "settings://connectors/github", now)
        self.assertEqual(notice["secret_fields"], [])

    def test_provider_expectation_validates(self):
        self.assertTrue(validate_provider_expectation(dict(EXPECTATION)))

    def test_provider_compatibility_happy_path(self):
        result = evaluate_provider_compatibility(BASE, EXPECTATION, OBSERVED)
        self.assertEqual(
            result,
            {"compatible": True, "issues": [], "requires_user_action": False},
        )

    def test_deprecated_auth_requires_migration(self):
        state = dict(BASE, auth_method="api_key")
        observed = dict(OBSERVED, auth_method="api_key")
        result = evaluate_provider_compatibility(state, EXPECTATION, observed)
        self.assertIn("auth_method_deprecated", result["issues"])
        self.assertIn("auth_method_migration_required", result["issues"])
        self.assertTrue(result["requires_user_action"])

    def test_setup_version_change_is_detected(self):
        result = evaluate_provider_compatibility(
            BASE,
            EXPECTATION,
            dict(OBSERVED, setup_version="2026-08"),
        )
        self.assertIn("setup_version_changed", result["issues"])

    def test_old_client_version_is_detected(self):
        result = evaluate_provider_compatibility(
            BASE,
            EXPECTATION,
            dict(OBSERVED, client_version="1.3.9"),
        )
        self.assertIn("client_version_too_old", result["issues"])

    def test_semantic_version_order_does_not_use_lexical_compare(self):
        result = evaluate_provider_compatibility(
            BASE,
            EXPECTATION,
            dict(OBSERVED, client_version="1.10.0"),
        )
        self.assertNotIn("client_version_too_old", result["issues"])

    def test_malformed_client_version_fails_closed(self):
        with self.assertRaises(ContractError):
            evaluate_provider_compatibility(
                BASE,
                EXPECTATION,
                dict(OBSERVED, client_version="v1.4"),
            )

    def test_cross_connector_observation_fails_closed(self):
        with self.assertRaises(ContractError):
            evaluate_provider_compatibility(
                BASE,
                EXPECTATION,
                dict(OBSERVED, connector_id="gmail"),
            )

    def test_observed_auth_must_match_canonical_state(self):
        with self.assertRaises(ContractError):
            evaluate_provider_compatibility(
                BASE,
                EXPECTATION,
                dict(OBSERVED, auth_method="api_key"),
            )

    def test_expected_auth_cannot_also_be_deprecated(self):
        with self.assertRaises(ContractError):
            validate_provider_expectation(
                dict(EXPECTATION, deprecated_auth_methods=["oauth"])
            )

    def test_unknown_provider_fields_fail_closed(self):
        expectation = dict(EXPECTATION)
        expectation["secret"] = "nope"
        with self.assertRaises(ContractError):
            validate_provider_expectation(expectation)

    def test_provider_incompatibility_canonically_blocks_ready(self):
        result = apply_provider_compatibility(
            BASE,
            EXPECTATION,
            dict(OBSERVED, setup_version="2026-08"),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["health"], "setup_required")
        self.assertEqual(result["issue_code"], "setup_version_changed")
        self.assertTrue(validate_connector_state(result))

    def test_auth_migration_uses_deprecated_health_and_notice(self):
        now = datetime.now(timezone.utc)
        state = dict(BASE, auth_method="api_key")
        observed = dict(OBSERVED, auth_method="api_key")
        result = apply_provider_compatibility(state, EXPECTATION, observed)
        self.assertFalse(result["ready"])
        self.assertEqual(result["health"], "deprecated")
        self.assertEqual(result["issue_code"], "auth_method_deprecated")
        notice = build_notice(result, "settings://connectors/github", now)
        self.assertTrue(should_surface(notice, result, now))

    def test_compatible_provider_keeps_ready_without_mutating_input(self):
        original = dict(BASE)
        result = apply_provider_compatibility(BASE, EXPECTATION, OBSERVED)
        self.assertEqual(result, BASE)
        self.assertIsNot(result, BASE)
        self.assertEqual(BASE, original)

    def test_should_surface_rejects_naive_current_time(self):
        state = dict(BASE)
        state.update(ready=False, health="setup_required", issue_code="setup")
        with self.assertRaises(ContractError):
            should_surface(None, state, datetime.now())

    def test_should_surface_rejects_malformed_dismiss_timestamp(self):
        now = datetime.now(timezone.utc)
        state = dict(BASE)
        state.update(ready=False, health="setup_required", issue_code="setup")
        notice = build_notice(state, "settings://connectors/github", now)
        notice["dismiss_until"] = "not-a-time"
        with self.assertRaises(ContractError):
            should_surface(notice, state, now)


if __name__ == "__main__":
    unittest.main()
