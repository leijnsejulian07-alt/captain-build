from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest

from connector_notice_runtime import ConnectorNoticeStore
from connector_settings_contract import ContractError


def state(project: str = "project-a", connector: str = "github", *, ready: bool = False, issue: str = "reauth_required") -> dict:
    if ready:
        return {
            "schema_version": 1,
            "connector_id": connector,
            "project_id": project,
            "installed": True,
            "connected": True,
            "enabled": True,
            "ready": True,
            "auth_method": "oauth",
            "health": "healthy",
            "permissions_granted": ["repo"],
            "permissions_required": ["repo"],
            "issue_code": None,
        }
    return {
        "schema_version": 1,
        "connector_id": connector,
        "project_id": project,
        "installed": True,
        "connected": True,
        "enabled": True,
        "ready": False,
        "auth_method": "oauth",
        "health": "expired_auth" if issue == "reauth_required" else "setup_required",
        "permissions_granted": ["repo"],
        "permissions_required": ["repo"],
        "issue_code": issue,
    }


class ConnectorNoticeRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "notices.sqlite3")
        self.now = datetime(2026, 9, 14, 3, 30, tzinfo=timezone.utc)
        self.path = "settings://connectors/github"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_unresolved_notice_surfaces_and_persists_across_restart(self) -> None:
        first = ConnectorNoticeStore(self.db)
        notice = first.evaluate(state(), self.path, self.now)
        self.assertEqual(notice["issue_code"], "reauth_required")
        second = ConnectorNoticeStore(self.db)
        self.assertIsNotNone(second.evaluate(state(), self.path, self.now + timedelta(minutes=1)))

    def test_dismissal_survives_restart_then_reappears(self) -> None:
        first = ConnectorNoticeStore(self.db)
        first.evaluate(state(), self.path, self.now)
        first.dismiss(state(), self.now, duration=timedelta(hours=6))
        second = ConnectorNoticeStore(self.db)
        self.assertIsNone(second.evaluate(state(), self.path, self.now + timedelta(hours=5)))
        self.assertIsNotNone(second.evaluate(state(), self.path, self.now + timedelta(hours=6, seconds=1)))

    def test_issue_change_breaks_old_dismissal_immediately(self) -> None:
        store = ConnectorNoticeStore(self.db)
        store.evaluate(state(), self.path, self.now)
        store.dismiss(state(), self.now, duration=timedelta(days=1))
        changed = state(issue="permissions_missing")
        notice = store.evaluate(changed, self.path, self.now + timedelta(minutes=10))
        self.assertEqual(notice["issue_code"], "permissions_missing")

    def test_permission_requirement_change_breaks_same_issue_dismissal(self) -> None:
        store = ConnectorNoticeStore(self.db)
        original = state(issue="permissions_missing")
        original["permissions_granted"] = []
        original["permissions_required"] = ["repo"]
        store.evaluate(original, self.path, self.now)
        store.dismiss(original, self.now, duration=timedelta(days=1))

        changed = dict(original)
        changed["permissions_required"] = ["repo", "write"]
        self.assertIsNotNone(store.evaluate(changed, self.path, self.now + timedelta(minutes=5)))

    def test_auth_or_health_change_breaks_same_issue_dismissal(self) -> None:
        store = ConnectorNoticeStore(self.db)
        original = state()
        store.evaluate(original, self.path, self.now)
        store.dismiss(original, self.now, duration=timedelta(days=1))

        auth_changed = dict(original)
        auth_changed["auth_method"] = "api_key"
        self.assertIsNotNone(store.evaluate(auth_changed, self.path, self.now + timedelta(minutes=5)))
        store.dismiss(auth_changed, self.now + timedelta(minutes=5), duration=timedelta(days=1))

        health_changed = dict(auth_changed)
        health_changed["health"] = "setup_required"
        self.assertIsNotNone(store.evaluate(health_changed, self.path, self.now + timedelta(minutes=10)))

    def test_ready_state_auto_clears_persisted_notice(self) -> None:
        store = ConnectorNoticeStore(self.db)
        store.evaluate(state(), self.path, self.now)
        self.assertEqual(len(store.persisted_rows()), 1)
        self.assertIsNone(store.evaluate(state(ready=True), self.path, self.now + timedelta(minutes=1)))
        self.assertEqual(store.persisted_rows(), [])

    def test_project_scopes_do_not_share_dismissal(self) -> None:
        store = ConnectorNoticeStore(self.db)
        store.evaluate(state(project="project-a"), self.path, self.now)
        store.dismiss(state(project="project-a"), self.now, duration=timedelta(days=1))
        self.assertIsNone(store.evaluate(state(project="project-a"), self.path, self.now + timedelta(hours=1)))
        self.assertIsNotNone(store.evaluate(state(project="project-b"), self.path, self.now + timedelta(hours=1)))
        self.assertEqual(len(store.persisted_rows()), 2)

    def test_connector_scopes_do_not_share_dismissal(self) -> None:
        store = ConnectorNoticeStore(self.db)
        store.evaluate(state(connector="github"), self.path, self.now)
        store.dismiss(state(connector="github"), self.now, duration=timedelta(days=1))
        other_path = "settings://connectors/drive"
        self.assertIsNotNone(store.evaluate(state(connector="drive"), other_path, self.now + timedelta(hours=1)))

    def test_persistence_contains_no_raw_connector_or_project_ids(self) -> None:
        store = ConnectorNoticeStore(self.db)
        store.evaluate(state(project="super-secret-project", connector="private-provider"), "settings://connectors/private-provider", self.now)
        rows = store.persisted_rows()
        self.assertEqual(len(rows), 1)
        flattened = "|".join("" if value is None else str(value) for value in rows[0])
        self.assertNotIn("super-secret-project", flattened)
        self.assertNotIn("private-provider", flattened)
        self.assertNotIn("reauth_required", flattened)

    def test_dismissal_cannot_hide_problem_longer_than_seven_days(self) -> None:
        store = ConnectorNoticeStore(self.db)
        with self.assertRaises(ContractError):
            store.dismiss(state(), self.now, duration=timedelta(days=8))

    def test_resolved_connector_cannot_be_dismissed(self) -> None:
        store = ConnectorNoticeStore(self.db)
        with self.assertRaises(ContractError):
            store.dismiss(state(ready=True), self.now)


if __name__ == "__main__":
    unittest.main()
