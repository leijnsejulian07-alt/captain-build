"""Integration regression: provider permission revocation reaches scoped Captain Settings."""

from src.captain.connector_actions import ConnectResult, ConnectionTestResult, ConnectorActionService
from src.captain.connector_control_center import ConnectorControlCenter
from src.captain.connector_event_bridge import ConnectorEventBridge, ConnectorEventKind
from src.captain.connector_settings import (
    AuthMethod,
    ConnectorHealth,
    ConnectorSettingsRegistry,
    ConnectorSetupSpec,
    ConnectorState,
)


class RevocableAdapter:
    def __init__(self) -> None:
        self.permissions = ("repo:read", "issues:write")

    def connect(self, *, project_id, credential_handle):
        return ConnectResult(
            connected=True,
            auth_material_present=True,
            granted_permissions=self.permissions,
        )

    def test_connection(self, *, project_id):
        return ConnectionTestResult(
            ok=True,
            health=ConnectorHealth.HEALTHY,
            safe_message="Provider reachable",
            permissions_authoritative=True,
            granted_permissions=self.permissions,
        )


def project_state(project_id: str) -> ConnectorState:
    return ConnectorState(
        connector_id="github",
        project_id=project_id,
        installed=True,
        connected=True,
        enabled=True,
        auth_method=AuthMethod.OAUTH,
        permissions=frozenset({"repo:read", "issues:write"}),
        required_permissions=frozenset({"repo:read", "issues:write"}),
        health=ConnectorHealth.HEALTHY,
        auth_material_present=True,
    )


def main() -> None:
    registry = ConnectorSettingsRegistry()
    registry.put(project_state("project-a"))
    registry.put(project_state("project-b"))

    adapter = RevocableAdapter()
    actions = ConnectorActionService(registry)
    actions.register(ConnectorSetupSpec("github", AuthMethod.OAUTH), adapter)
    bridge = ConnectorEventBridge(registry)
    control = ConnectorControlCenter(registry, actions, bridge)

    # Prime both project views so later events represent an actual change.
    control.snapshot(project_id="project-a", now=100.0)
    control.snapshot(project_id="project-b", now=100.0)

    # Provider revokes one required permission for project A.
    adapter.permissions = ("repo:read",)
    revoked = control.perform(
        "github",
        "test_connection",
        project_id="project-a",
        now=101.0,
        user_initiated=True,
    )
    state_a = registry.get("github", project_id="project-a")
    state_b = registry.get("github", project_id="project-b")
    assert state_a is not None and not state_a.ready
    assert state_a.permissions == frozenset({"repo:read"})
    assert state_b is not None and state_b.ready

    assert any(
        event.kind is ConnectorEventKind.STATUS_CHANGED
        and event.project_id == "project-a"
        and event.payload["ready"] is False
        for event in revoked.events
    )
    assert any(
        event.kind is ConnectorEventKind.REMEDIATION_OPENED
        and event.project_id == "project-a"
        and event.payload["reason"] == "Required permissions are missing"
        for event in revoked.events
    )
    assert any(
        banner["connector_id"] == "github"
        and banner["project_id"] == "project-a"
        and banner["reason"] == "Required permissions are missing"
        for banner in revoked.snapshot.banners
    )

    # The revoked project's events/notices never become visible in project B.
    b_view = control.snapshot(project_id="project-b", now=101.0)
    assert not any(banner["project_id"] == "project-a" for banner in b_view.banners)
    assert not bridge.events_since(0, project_id="project-b")[-1].project_id == "project-a"

    # Provider restores the missing permission. Ready recovers and remediation clears.
    adapter.permissions = ("repo:read", "issues:write")
    recovered = control.perform(
        "github",
        "test_connection",
        project_id="project-a",
        now=102.0,
        user_initiated=True,
    )
    state_a = registry.get("github", project_id="project-a")
    assert state_a is not None and state_a.ready
    assert any(
        event.kind is ConnectorEventKind.REMEDIATION_CLEARED
        and event.project_id == "project-a"
        for event in recovered.events
    )
    assert not any(banner["project_id"] == "project-a" for banner in recovered.snapshot.banners)

    # No auth material or credential references may enter UI-visible state/events.
    rendered = (
        repr(revoked.snapshot.safe_payload())
        + repr(revoked.events)
        + repr(recovered.snapshot.safe_payload())
        + repr(recovered.events)
    ).lower()
    for forbidden in ("password", "api_key", "apikey", "authorization", "credential_handle"):
        assert forbidden not in rendered

    print("CONNECTOR_REVOCATION_CONTROL_CENTER_PASS")


if __name__ == "__main__":
    main()