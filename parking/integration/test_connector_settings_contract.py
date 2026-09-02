from datetime import datetime, timedelta, timezone
import unittest

from connector_settings_contract import ContractError, build_notice, should_surface, validate_connector_state


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


if __name__ == "__main__":
    unittest.main()
