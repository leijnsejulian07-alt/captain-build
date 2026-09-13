from datetime import datetime, timedelta, timezone
import unittest

from connector_health_runtime import (
    apply_connection_probe,
    build_test_connection_request,
    connector_status_view,
    validate_connection_probe,
    validate_test_connection_request,
)
from connector_settings_contract import ContractError, validate_connector_state


NOW = datetime(2026, 9, 13, 9, 15, tzinfo=timezone.utc)

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
    "permissions_granted": ["read", "repo"],
    "permissions_required": ["read", "repo"],
    "issue_code": None,
}


def request_for(state=BASE):
    return build_test_connection_request(state, NOW - timedelta(minutes=1))


def probe_for(state=BASE, **changes):
    request = request_for(state)
    probe = {
        "schema_version": 1,
        "connector_id": state["connector_id"],
        "project_id": state["project_id"],
        "auth_method": state["auth_method"],
        "observed_at": NOW.isoformat(),
        "provider_status": "reachable",
        "auth_status": "valid",
        "permissions_granted": list(state["permissions_granted"]),
        "request_digest": request["request_digest"],
        "secret_fields": [],
    }
    probe.update(changes)
    return probe


class ConnectorHealthRuntimeTests(unittest.TestCase):
    def test_test_connection_request_is_explicit_metadata_only(self):
        request = request_for()
        self.assertTrue(request["explicit_user_action_required"])
        self.assertFalse(request["allow_paid_activation"])
        self.assertEqual(request["secret_fields"], [])
        self.assertEqual(
            request["checks"],
            ["provider_reachability", "auth_validity", "permissions"],
        )

    def test_uninstalled_connector_cannot_test_connection(self):
        state = dict(BASE, installed=False, connected=False, enabled=False, ready=False)
        state["health"] = "setup_required"
        state["issue_code"] = "install_required"
        with self.assertRaises(ContractError):
            build_test_connection_request(state, NOW)

    def test_happy_probe_keeps_ready(self):
        result = apply_connection_probe(BASE, probe_for(), NOW, request=request_for())
        self.assertTrue(result["ready"])
        self.assertEqual(result["health"], "healthy")
        self.assertIsNone(result["issue_code"])

    def test_expired_credentials_fail_closed_without_disconnect_side_effect(self):
        result = apply_connection_probe(
            BASE, probe_for(auth_status="expired"), NOW, request=request_for()
        )
        self.assertFalse(result["ready"])
        self.assertTrue(result["connected"])
        self.assertEqual(result["health"], "expired_auth")
        self.assertEqual(result["issue_code"], "reauth_required")

    def test_invalid_credentials_fail_closed(self):
        result = apply_connection_probe(
            BASE, probe_for(auth_status="invalid"), NOW, request=request_for()
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["health"], "invalid_auth")
        self.assertEqual(result["issue_code"], "credentials_invalid")

    def test_provider_outage_is_degraded_not_auth_rewritten(self):
        result = apply_connection_probe(
            BASE, probe_for(provider_status="unreachable"), NOW, request=request_for()
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["health"], "degraded")
        self.assertEqual(result["auth_method"], "oauth")
        self.assertEqual(result["issue_code"], "provider_unreachable")

    def test_stale_probe_cannot_restore_ready(self):
        stale = probe_for(observed_at=(NOW - timedelta(days=2)).isoformat())
        result = apply_connection_probe(BASE, stale, NOW, request=request_for())
        self.assertFalse(result["ready"])
        self.assertEqual(result["issue_code"], "connection_test_stale")

    def test_future_probe_fails_closed(self):
        future = probe_for(observed_at=(NOW + timedelta(minutes=6)).isoformat())
        with self.assertRaises(ContractError):
            apply_connection_probe(BASE, future, NOW, request=request_for())

    def test_cross_project_probe_fails_closed(self):
        with self.assertRaises(ContractError):
            apply_connection_probe(
                BASE, probe_for(project_id="project-b"), NOW, request=request_for()
            )

    def test_auth_method_mismatch_fails_closed(self):
        with self.assertRaises(ContractError):
            apply_connection_probe(
                BASE, probe_for(auth_method="api_key"), NOW, request=request_for()
            )

    def test_missing_permission_is_canonical_setup_issue(self):
        result = apply_connection_probe(
            BASE, probe_for(permissions_granted=["read"]), NOW, request=request_for()
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["health"], "setup_required")
        self.assertEqual(result["issue_code"], "permissions_missing")
        self.assertTrue(validate_connector_state(result))

    def test_probe_does_not_enable_disabled_connector(self):
        disabled = dict(BASE, enabled=False, ready=False)
        probe = probe_for(disabled)
        result = apply_connection_probe(disabled, probe, NOW, request=request_for(disabled))
        self.assertFalse(result["enabled"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["health"], "healthy")

    def test_disconnected_connector_is_not_silently_connected(self):
        disconnected = dict(BASE, connected=False, ready=False)
        disconnected["health"] = "setup_required"
        disconnected["issue_code"] = "connect_required"
        probe = probe_for(disconnected)
        result = apply_connection_probe(disconnected, probe, NOW, request=request_for(disconnected))
        self.assertFalse(result["connected"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["issue_code"], "connect_required")

    def test_status_view_explicitly_separates_five_settings_axes(self):
        state = dict(BASE, ready=False)
        state["permissions_granted"] = ["read"]
        state["health"] = "setup_required"
        state["issue_code"] = "permissions_missing"
        view = connector_status_view(state)
        self.assertTrue(view["installed"])
        self.assertTrue(view["connected"])
        self.assertTrue(view["enabled"])
        self.assertFalse(view["ready"])
        self.assertEqual(view["permissions"]["missing"], ["repo"])
        self.assertEqual(view["secret_fields"], [])

    def test_probe_must_match_exact_explicit_request(self):
        other_request = build_test_connection_request(BASE, NOW - timedelta(minutes=2))
        with self.assertRaises(ContractError):
            apply_connection_probe(BASE, probe_for(), NOW, request=other_request)

    def test_stale_explicit_request_is_refused(self):
        old_request = build_test_connection_request(BASE, NOW - timedelta(days=2))
        probe = probe_for()
        probe["request_digest"] = old_request["request_digest"]
        with self.assertRaises(ContractError):
            apply_connection_probe(BASE, probe, NOW, request=old_request)

    def test_test_request_tampering_is_refused(self):
        request = request_for()
        request["allow_paid_activation"] = True
        with self.assertRaises(ContractError):
            validate_test_connection_request(request)

    def test_probe_rejects_secret_or_unknown_payload_fields(self):
        probe = probe_for()
        probe["token"] = "must-never-be-accepted"
        with self.assertRaises(ContractError):
            validate_connection_probe(probe)

    def test_probe_requires_explicit_empty_secret_fields(self):
        probe = probe_for(secret_fields=["token"])
        with self.assertRaises(ContractError):
            validate_connection_probe(probe)


if __name__ == "__main__":
    unittest.main()
