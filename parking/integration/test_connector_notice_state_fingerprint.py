from datetime import datetime, timedelta, timezone
import unittest

from connector_settings_contract import build_notice, connector_problem_fingerprint, should_surface


BASE = {
    "schema_version": 1,
    "connector_id": "github",
    "project_id": "project-a",
    "installed": True,
    "connected": True,
    "enabled": True,
    "ready": False,
    "auth_method": "oauth",
    "health": "setup_required",
    "permissions_granted": ["read"],
    "permissions_required": ["read", "repo"],
    "issue_code": "setup_required",
}


class ConnectorNoticeStateFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 14, 5, 30, tzinfo=timezone.utc)
        self.path = "settings://connectors/github"

    def _dismissed_notice(self, state: dict) -> dict:
        notice = build_notice(state, self.path, self.now, self.now + timedelta(hours=6))
        self.assertIsNotNone(notice)
        return notice

    def test_permission_requirement_change_invalidates_rendered_dismissal(self) -> None:
        notice = self._dismissed_notice(dict(BASE))
        changed = dict(BASE, permissions_required=["read", "repo", "write"])
        self.assertNotEqual(notice["notice_fingerprint"], connector_problem_fingerprint(changed))
        self.assertTrue(should_surface(notice, changed, self.now + timedelta(minutes=5)))

    def test_auth_change_with_same_issue_code_invalidates_rendered_dismissal(self) -> None:
        notice = self._dismissed_notice(dict(BASE))
        changed = dict(BASE, auth_method="api_key")
        self.assertTrue(should_surface(notice, changed, self.now + timedelta(minutes=5)))

    def test_health_change_with_same_issue_code_invalidates_rendered_dismissal(self) -> None:
        notice = self._dismissed_notice(dict(BASE))
        changed = dict(BASE, health="degraded")
        self.assertTrue(should_surface(notice, changed, self.now + timedelta(minutes=5)))

    def test_enablement_change_with_same_issue_code_invalidates_rendered_dismissal(self) -> None:
        notice = self._dismissed_notice(dict(BASE))
        changed = dict(BASE, enabled=False)
        self.assertTrue(should_surface(notice, changed, self.now + timedelta(minutes=5)))

    def test_permission_order_does_not_change_fingerprint(self) -> None:
        first = dict(BASE, permissions_granted=["read", "repo"], permissions_required=["read", "repo", "write"])
        second = dict(first, permissions_granted=["repo", "read"], permissions_required=["write", "repo", "read"])
        self.assertEqual(connector_problem_fingerprint(first), connector_problem_fingerprint(second))

    def test_same_problem_stays_dismissed_until_deadline(self) -> None:
        state = dict(BASE)
        notice = self._dismissed_notice(state)
        self.assertFalse(should_surface(notice, state, self.now + timedelta(hours=5)))
        self.assertTrue(should_surface(notice, state, self.now + timedelta(hours=7)))

    def test_fingerprint_is_opaque_and_secret_free(self) -> None:
        fingerprint = connector_problem_fingerprint(dict(BASE))
        self.assertEqual(len(fingerprint), 64)
        self.assertNotIn("github", fingerprint)
        self.assertNotIn("project-a", fingerprint)
        self.assertNotIn("setup_required", fingerprint)


if __name__ == "__main__":
    unittest.main()
