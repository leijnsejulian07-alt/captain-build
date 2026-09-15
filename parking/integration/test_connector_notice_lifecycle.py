from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from connector_notice_lifecycle import project_notice_lifecycle
from connector_settings_contract import build_notice


def state(*, ready: bool = False) -> dict:
    return {
        "schema_version": 1,
        "connector_id": "github",
        "project_id": "project-a",
        "installed": True,
        "connected": True,
        "enabled": True,
        "ready": ready,
        "auth_method": "oauth",
        "health": "healthy" if ready else "expired_auth",
        "permissions_granted": ["repo"],
        "permissions_required": ["repo"],
        "issue_code": None if ready else "reauth_required",
    }


class ConnectorNoticeLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 14, 6, 15, tzinfo=timezone.utc)
        self.path = "settings://connectors/github"

    def test_unresolved_without_notice_is_visible(self) -> None:
        projected = project_notice_lifecycle(state(), None, self.now)
        self.assertEqual(projected["status"], "visible")
        self.assertEqual(projected["reason"], "action_required")
        self.assertTrue(projected["show_banner"])

    def test_temporary_dismissal_projects_reminder(self) -> None:
        until = self.now + timedelta(hours=6)
        notice = build_notice(state(), self.path, self.now, dismiss_until=until)
        projected = project_notice_lifecycle(state(), notice, self.now + timedelta(hours=1))
        self.assertEqual(projected["status"], "temporarily_dismissed")
        self.assertEqual(projected["reason"], "temporarily_dismissed")
        self.assertFalse(projected["show_banner"])
        self.assertEqual(projected["reminder_at"], until.isoformat())

    def test_expired_dismissal_becomes_visible_again(self) -> None:
        until = self.now + timedelta(hours=2)
        notice = build_notice(state(), self.path, self.now, dismiss_until=until)
        projected = project_notice_lifecycle(state(), notice, until + timedelta(seconds=1))
        self.assertEqual(projected["status"], "visible")
        self.assertEqual(projected["reason"], "reminder_due")
        self.assertTrue(projected["show_banner"])

    def test_problem_change_invalidates_old_dismissal_immediately(self) -> None:
        notice = build_notice(state(), self.path, self.now, dismiss_until=self.now + timedelta(days=1))
        changed = state()
        changed["health"] = "setup_required"
        projected = project_notice_lifecycle(changed, notice, self.now + timedelta(minutes=5))
        self.assertEqual(projected["status"], "visible")
        self.assertEqual(projected["reason"], "problem_changed")
        self.assertTrue(projected["show_banner"])

    def test_ready_state_is_resolved_and_has_no_deep_link(self) -> None:
        projected = project_notice_lifecycle(state(ready=True), None, self.now)
        self.assertEqual(projected["status"], "resolved")
        self.assertEqual(projected["reason"], "connector_ready")
        self.assertFalse(projected["show_banner"])
        self.assertIsNone(projected["remediation_path"])

    def test_projection_does_not_expose_scope_identity_or_secrets(self) -> None:
        notice = build_notice(state(), self.path, self.now)
        projected = project_notice_lifecycle(state(), notice, self.now)
        self.assertNotIn("connector_id", projected)
        self.assertNotIn("project_id", projected)
        self.assertEqual(projected["secret_fields"], [])
        flattened = repr(projected)
        self.assertNotIn("project-a", flattened)
        self.assertNotIn("github", flattened.replace(self.path, ""))


if __name__ == "__main__":
    unittest.main()
