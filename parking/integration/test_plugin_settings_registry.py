from __future__ import annotations

import unittest

from plugin_settings_registry import (
    PluginSettingsError,
    authorize_plugin_dispatch,
    build_plugin_settings_projection,
    parse_plugin_state,
)


def plugin(plugin_id: str, **overrides):
    value = {
        "schema_version": 1,
        "plugin_id": plugin_id,
        "installed": True,
        "connected": True,
        "enabled": True,
        "ready": True,
        "auth_method": "oauth",
        "scope": "global",
        "project_id": None,
        "capabilities": ["research.search", "repo.read"],
        "permissions": ["read.content"],
        "health": "healthy",
    }
    value.update(overrides)
    return value


class PluginSettingsRegistryTests(unittest.TestCase):
    def test_ready_global_plugin_can_dispatch_declared_capability(self):
        result = authorize_plugin_dispatch(
            [plugin("github")], plugin_id="github", capability="repo.read"
        )
        self.assertTrue(result["allowed"])
        self.assertEqual(result["secret_fields"], [])

    def test_disabled_unready_or_unhealthy_plugin_cannot_dispatch(self):
        cases = [
            plugin("a", enabled=False, ready=False),
            plugin("b", connected=False, ready=False),
            plugin("c", health="blocked", ready=False),
        ]
        for item in cases:
            result = authorize_plugin_dispatch(
                [item], plugin_id=item["plugin_id"], capability="repo.read"
            )
            self.assertFalse(result["allowed"])

    def test_undeclared_capability_is_denied(self):
        result = authorize_plugin_dispatch(
            [plugin("github")], plugin_id="github", capability="repo.write"
        )
        self.assertFalse(result["allowed"])

    def test_project_plugin_is_exact_project_bound(self):
        record = plugin(
            "builder-tools",
            scope="project",
            project_id="project-a",
            auth_method="local",
            capabilities=["builder.preview"],
        )
        allowed = authorize_plugin_dispatch(
            [record], plugin_id="builder-tools", capability="builder.preview", project_id="project-a"
        )
        denied = authorize_plugin_dispatch(
            [record], plugin_id="builder-tools", capability="builder.preview", project_id="project-b"
        )
        self.assertTrue(allowed["allowed"])
        self.assertFalse(denied["allowed"])

    def test_settings_projection_hides_other_project_plugins(self):
        projection = build_plugin_settings_projection(
            [
                plugin("global"),
                plugin("mine", scope="project", project_id="project-a", auth_method="local"),
                plugin("foreign", scope="project", project_id="project-b", auth_method="local"),
            ],
            project_id="project-a",
        )
        self.assertEqual([p["plugin_id"] for p in projection["plugins"]], ["global", "mine"])
        self.assertNotIn("project-a", repr(projection))
        self.assertNotIn("project-b", repr(projection))

    def test_installed_connected_enabled_ready_are_distinct_and_fail_closed(self):
        with self.assertRaises(PluginSettingsError):
            parse_plugin_state(plugin("bad", installed=False))
        with self.assertRaises(PluginSettingsError):
            parse_plugin_state(plugin("bad2", enabled=False, ready=True))
        with self.assertRaises(PluginSettingsError):
            parse_plugin_state(plugin("bad3", health="degraded", ready=True))

    def test_duplicate_plugin_id_fails_closed(self):
        with self.assertRaises(PluginSettingsError):
            build_plugin_settings_projection([plugin("same"), plugin("same")])

    def test_secret_or_schema_expansion_is_rejected(self):
        secret = plugin("secret")
        secret["access_token"] = "not-a-real-token"
        with self.assertRaises(PluginSettingsError):
            parse_plugin_state(secret)
        extra = plugin("extra")
        extra["display_name"] = "Extra"
        with self.assertRaises(PluginSettingsError):
            parse_plugin_state(extra)

    def test_unknown_plugin_authority_fails_closed(self):
        with self.assertRaises(PluginSettingsError):
            authorize_plugin_dispatch([], plugin_id="missing", capability="repo.read")


if __name__ == "__main__":
    unittest.main()
