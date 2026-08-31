import unittest

from settings_plugin_registry import PluginManifest, build_registry, build_launch_notices


def good(**overrides):
    data = dict(
        plugin_id="github",
        name="GitHub",
        kind="connector",
        auth_method="oauth",
        installed=True,
        connected=True,
        enabled=True,
        permissions=("repo.read", "repo.write"),
        required_permissions=("repo.read",),
        version="1.0",
        setup_version=2,
        verified_setup_version=2,
        health="ok",
    )
    data.update(overrides)
    return PluginManifest(**data)


class RegistryTests(unittest.TestCase):
    def test_ready_requires_all_gates(self):
        self.assertTrue(good().ready)
        self.assertFalse(good(connected=False).ready)
        self.assertFalse(good(enabled=False).ready)
        self.assertFalse(good(health="expired").ready)
        self.assertFalse(good(verified_setup_version=1).ready)

    def test_connected_or_enabled_without_install_fails(self):
        with self.assertRaises(ValueError):
            good(installed=False).validate()

    def test_required_permission_must_be_declared(self):
        with self.assertRaises(ValueError):
            good(required_permissions=("admin",)).validate()

    def test_path_like_ids_fail_closed(self):
        for bad in ("../github", "git/hub", "github\\x", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                good(plugin_id=bad).validate()

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            build_registry([good(), good(name="Other")])

    def test_public_state_has_no_secret_fields(self):
        state = good().public_state()
        forbidden = {"token", "api_key", "secret", "password", "authorization", "cookie"}
        self.assertFalse(forbidden & set(state))
        self.assertEqual(state["settings_anchor"], "plugin-github")

    def test_local_plugin_does_not_require_connected(self):
        p = good(plugin_id="openbuilder", name="OpenBuilder", kind="builder", auth_method="local", connected=False)
        self.assertTrue(p.ready)

    def test_registry_order_is_stable(self):
        a = good(plugin_id="zeta", name="Zeta")
        b = good(plugin_id="alpha", name="Alpha", kind="skill", auth_method="none", connected=False)
        rows = build_registry([b, a])
        self.assertEqual([r["id"] for r in rows], ["zeta", "alpha"])

    def test_diagnostics_drive_safe_remediation(self):
        self.assertEqual(good(connected=False).next_action, "connect")
        self.assertEqual(good(verified_setup_version=1).next_action, "update-setup")
        self.assertEqual(good(health="degraded").next_action, "test-connection")
        self.assertIsNone(good().next_action)

    def test_remediation_priority_is_deterministic(self):
        p = good(enabled=False, connected=False, verified_setup_version=1, health="degraded")
        self.assertEqual(p.next_action, "enable")
        self.assertEqual(
            p.diagnostics(),
            ("disabled", "connect-required", "setup-verification-required", "health-degraded"),
        )

    def test_health_and_verified_setup_values_fail_closed(self):
        with self.assertRaises(ValueError):
            good(health="garbage").validate()
        for bad in (True, 0, -1, 2**31):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                good(verified_setup_version=bad).validate()

    def test_test_connection_is_explicit_for_key_id_or_local_auth(self):
        self.assertFalse(good().public_state()["test_connection_available"])
        self.assertTrue(good(auth_method="api-key").public_state()["test_connection_available"])
        self.assertTrue(good(auth_method="id").public_state()["test_connection_available"])
        self.assertTrue(good(auth_method="local").public_state()["test_connection_available"])

    def test_launch_notice_for_enabled_unresolved_setup(self):
        notices = build_launch_notices([good(connected=False)], now=1000)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["action"], "connect")
        self.assertEqual(notices[0]["settings_anchor"], "plugin-github")
        self.assertEqual(len(notices[0]["notice_state_id"]), 64)
        self.assertNotIn("permissions", notices[0])

    def test_launch_notice_clears_when_resolved_and_ignores_disabled_optional(self):
        self.assertEqual(build_launch_notices([good()], now=1000), [])
        self.assertEqual(build_launch_notices([good(enabled=False, connected=False)], now=1000), [])
        self.assertEqual(build_launch_notices([good(installed=False, connected=False, enabled=False)], now=1000), [])

    def test_dismissal_is_temporary_and_bounded(self):
        p = good(connected=False)
        notice = build_launch_notices([p], now=1000)[0]
        dismissal = {"github": {"until": 1100, "notice_state_id": notice["notice_state_id"]}}
        self.assertEqual(build_launch_notices([p], dismissal, now=1000), [])
        dismissal["github"]["until"] = 999
        self.assertEqual(len(build_launch_notices([p], dismissal, now=1000)), 1)
        dismissal["github"]["until"] = 1000 + 7 * 24 * 60 * 60 + 1
        with self.assertRaises(ValueError):
            build_launch_notices([p], dismissal, now=1000)

    def test_changed_problem_does_not_inherit_old_dismissal(self):
        auth_problem = good(connected=False)
        auth_notice = build_launch_notices([auth_problem], now=1000)[0]
        dismissal = {"github": {"until": 1100, "notice_state_id": auth_notice["notice_state_id"]}}
        self.assertEqual(build_launch_notices([auth_problem], dismissal, now=1000), [])

        setup_problem = good(verified_setup_version=1)
        notices = build_launch_notices([setup_problem], dismissal, now=1000)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["action"], "update-setup")
        self.assertNotEqual(notices[0]["notice_state_id"], auth_notice["notice_state_id"])

    def test_same_action_but_changed_health_reappears(self):
        degraded = good(health="degraded")
        old_notice = build_launch_notices([degraded], now=1000)[0]
        dismissal = {"github": {"until": 1100, "notice_state_id": old_notice["notice_state_id"]}}
        expired = good(health="expired")
        notices = build_launch_notices([expired], dismissal, now=1000)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["action"], "test-connection")
        self.assertNotEqual(notices[0]["notice_state_id"], old_notice["notice_state_id"])

    def test_launch_notices_fail_closed_on_duplicate_or_bad_dismissal(self):
        with self.assertRaises(ValueError):
            build_launch_notices([good(), good(name="Other")], now=1000)
        p = good(connected=False)
        notice = build_launch_notices([p], now=1000)[0]
        bad_states = (
            True,
            1100,
            {"until": True, "notice_state_id": notice["notice_state_id"]},
            {"until": -1, "notice_state_id": notice["notice_state_id"]},
            {"until": 1100, "notice_state_id": "bad"},
            {"until": 1100, "notice_state_id": notice["notice_state_id"], "extra": True},
        )
        for bad in bad_states:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build_launch_notices([p], {"github": bad}, now=1000)


if __name__ == "__main__":
    unittest.main()
