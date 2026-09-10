"""Regression for Captain's canonical connector Settings presentation model."""
from src.captain.connector_actions import ConnectResult, ConnectionTestResult, ConnectorActionService
from src.captain.connector_settings import (
    AuthMethod, ConnectorError, ConnectorHealth, ConnectorSetupSpec,
    ConnectorSettingsRegistry, ConnectorState,
)
from src.captain.connector_settings_surface import ConnectorSettingsSurface


class Adapter:
    def connect(self, *, project_id, credential_handle):
        return ConnectResult(True, True)

    def test_connection(self, *, project_id):
        return ConnectionTestResult(True, ConnectorHealth.HEALTHY, "healthy")


def expect_error(fn):
    try:
        fn()
    except ConnectorError:
        return
    raise AssertionError("expected ConnectorError")


def main() -> None:
    registry = ConnectorSettingsRegistry()
    actions = ConnectorActionService(registry)
    actions.register(ConnectorSetupSpec("github", AuthMethod.OAUTH), Adapter())
    actions.register(ConnectorSetupSpec("custom", AuthMethod.API_KEY, ("API key", "workspace ID")), Adapter())

    registry.put(ConnectorState(
        "github", None, True, False, False, AuthMethod.OAUTH,
        required_permissions=frozenset({"repo:read"}), health=ConnectorHealth.UNKNOWN,
    ))
    registry.put(ConnectorState(
        "custom", "project-a", True, True, True, AuthMethod.API_KEY,
        permissions=frozenset({"read"}), required_permissions=frozenset({"read", "write"}),
        auth_material_present=True, health=ConnectorHealth.HEALTHY,
    ))
    surface = ConnectorSettingsSurface(registry, actions)

    # Normal/global Settings never expose another project's connector state.
    global_rows = surface.rows(project_id=None, now=0)
    assert [r.connector_id for r in global_rows] == ["github"]
    oauth = global_rows[0]
    assert oauth.setup_mode == "official_oauth"
    assert oauth.required_fields == ()
    assert oauth.actions == ("connect", "enable")

    # Project Settings may see global integrations plus only its exact project scope.
    project_rows = surface.rows(project_id="project-a", now=0)
    assert {(r.connector_id, r.project_id) for r in project_rows} == {
        ("github", None), ("custom", "project-a")
    }
    assert surface.rows(project_id="project-b", now=0) == global_rows
    custom = next(r for r in project_rows if r.connector_id == "custom")
    assert custom.setup_mode == "credential_store"
    assert custom.required_fields == ("API key", "workspace ID")
    assert "test_connection" in custom.actions
    assert "review_permissions" in custom.actions
    assert "open_remediation" in custom.actions
    assert custom.remediation["project_id"] == "project-a"

    # The UI payload distinguishes lifecycle state without ever exposing auth material.
    payload = custom.safe_payload()
    for key in ("installed", "connected", "enabled", "ready", "permissions", "auth_method"):
        assert key in payload
    assert "auth_material_present" not in payload
    assert "credential_handle" not in payload
    assert payload["settings_deep_link"] == "settings://connectors/custom"

    # Paid activation is explicit in the UI contract; never represented as plain enable.
    actions.register(ConnectorSetupSpec("paid", AuthMethod.LOCAL), Adapter())
    registry.put(ConnectorState(
        "paid", None, True, True, False, AuthMethod.LOCAL,
        health=ConnectorHealth.HEALTHY, paid_service=True,
    ))
    paid = next(r for r in surface.rows(project_id=None, now=0) if r.connector_id == "paid")
    assert "enable_with_approval" in paid.actions and "enable" not in paid.actions

    # Provider/setup auth drift fails closed instead of rendering a misleading Connect path.
    actions.register(ConnectorSetupSpec("drift", AuthMethod.OAUTH), Adapter())
    registry.put(ConnectorState("drift", None, True, False, False, AuthMethod.API_KEY))
    expect_error(lambda: surface.rows(project_id=None, now=0))

    print("CONNECTOR_SETTINGS_SURFACE_HARDENED_PASS")


if __name__ == "__main__":
    main()
