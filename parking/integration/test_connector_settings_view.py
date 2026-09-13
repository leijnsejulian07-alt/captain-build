from __future__ import annotations

import unittest

from connector_settings_contract import ContractError, build_notice
from connector_settings_view import build_connector_launch_projection, build_connector_settings_view
from datetime import datetime, timezone


NOW = datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc)


def state(**overrides):
    value = {
        "schema_version": 1,
        "connector_id": "github",
        "project_id": "project-a",
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
    value.update(overrides)
    return value


class ConnectorSettingsViewTests(unittest.TestCase):
    def test_ready_oauth_card_is_secret_free_and_testable(self):
        card = build_connector_settings_view(
            state(), remediation_path="settings://connectors/github"
        )
        self.assertTrue(card["status"]["ready"])
        self.assertFalse(card["paid_activation_allowed"])
        self.assertEqual(card["secret_fields"], [])
        self.assertEqual(
            [action["id"] for action in card["actions"]],
            ["test_connection", "disable"],
        )
        self.assertTrue(all(action["requires_user_action"] for action in card["actions"]))
        self.assertTrue(all(not action["may_activate_paid_service"] for action in card["actions"]))

    def test_disconnected_oauth_exposes_official_connect_flow(self):
        card = build_connector_settings_view(
            state(
                connected=False,
                ready=False,
                health="setup_required",
                issue_code="connect_required",
            ),
            remediation_path="settings://connectors/github",
        )
        self.assertEqual(
            [action["id"] for action in card["actions"]],
            ["connect", "test_connection", "disable"],
        )

    def test_api_key_uses_configuration_not_fake_oauth(self):
        card = build_connector_settings_view(
            state(
                connector_id="example-api",
                connected=False,
                ready=False,
                auth_method="api_key",
                health="setup_required",
                issue_code="credentials_required",
                permissions_granted=[],
                permissions_required=["read"],
            ),
            remediation_path="settings://connectors/example-api",
        )
        self.assertEqual(
            [action["id"] for action in card["actions"]],
            ["configure_credentials", "test_connection", "disable"],
        )
        self.assertNotIn("connect", [action["id"] for action in card["actions"]])

    def test_notice_must_match_connector_project_and_deep_link(self):
        unhealthy = state(
            ready=False,
            health="expired_auth",
            issue_code="reauth_required",
        )
        notice = build_notice(
            unhealthy, "settings://connectors/github", NOW
        )
        card = build_connector_settings_view(
            unhealthy,
            remediation_path="settings://connectors/github",
            active_notice=notice,
        )
        self.assertEqual(card["notice"]["issue_code"], "reauth_required")

        wrong = dict(notice)
        wrong["project_id"] = "project-b"
        with self.assertRaises(ContractError):
            build_connector_settings_view(
                unhealthy,
                remediation_path="settings://connectors/github",
                active_notice=wrong,
            )

    def test_ready_connector_rejects_stale_notice(self):
        unresolved = state(
            ready=False,
            health="degraded",
            issue_code="provider_unreachable",
        )
        notice = build_notice(unresolved, "settings://connectors/github", NOW)
        with self.assertRaises(ContractError):
            build_connector_settings_view(
                state(),
                remediation_path="settings://connectors/github",
                active_notice=notice,
            )

    def test_launch_projection_is_deterministic_and_counts_unresolved(self):
        other = state(
            connector_id="calendar",
            project_id="project-a",
            connected=False,
            ready=False,
            health="setup_required",
            issue_code="connect_required",
            permissions_granted=[],
            permissions_required=["calendar"],
        )
        projection = build_connector_launch_projection(
            [other, state()],
            remediation_paths={
                "github": "settings://connectors/github",
                "calendar": "settings://connectors/calendar",
            },
        )
        self.assertEqual(projection["unresolved_count"], 1)
        self.assertEqual(
            [card["connector_id"] for card in projection["connectors"]],
            ["calendar", "github"],
        )
        self.assertEqual(projection["secret_fields"], [])

    def test_duplicate_connector_state_fails_closed(self):
        with self.assertRaises(ContractError):
            build_connector_launch_projection(
                [state(), state()],
                remediation_paths={"github": "settings://connectors/github"},
            )

    def test_project_scopes_can_reuse_connector_id_without_collision(self):
        projection = build_connector_launch_projection(
            [state(project_id="project-a"), state(project_id="project-b")],
            remediation_paths={"github": "settings://connectors/github"},
        )
        self.assertEqual(projection["projects"], ["project-a", "project-b"])
        self.assertEqual(len(projection["connectors"]), 2)

    def test_missing_deep_link_fails_closed(self):
        with self.assertRaises(ContractError):
            build_connector_launch_projection([state()], remediation_paths={})


if __name__ == "__main__":
    unittest.main()
