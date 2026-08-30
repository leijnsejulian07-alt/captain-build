import unittest

from settings_plugin_registry import PluginManifest, build_registry


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


if __name__ == "__main__":
    unittest.main()
