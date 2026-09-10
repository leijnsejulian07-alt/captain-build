"""Regression for scoped, secret-free connector UI events and launch banners."""

from src.captain.connector_event_bridge import ConnectorEventBridge, ConnectorEventKind
from src.captain.connector_settings import (
    AuthMethod,
    ConnectorHealth,
    ConnectorSettingsRegistry,
    ConnectorState,
)


def main() -> None:
    registry = ConnectorSettingsRegistry()
    registry.put(ConnectorState(
        connector_id="github",
        project_id=None,
        installed=True,
        connected=True,
        enabled=True,
        auth_method=AuthMethod.OAUTH,
        permissions=frozenset({"repo:read"}),
        required_permissions=frozenset({"repo:read"}),
        health=ConnectorHealth.HEALTHY,
        version="1",
        auth_material_present=True,
        provider_auth_version="oauth2",
    ))
    registry.put(ConnectorState(
        connector_id="builder-provider",
        project_id="project-a",
        installed=True,
        connected=True,
        enabled=True,
        auth_method=AuthMethod.OAUTH,
        permissions=frozenset(),
        required_permissions=frozenset({"build:run"}),
        health=ConnectorHealth.HEALTHY,
        auth_material_present=True,
    ))

    bridge = ConnectorEventBridge(registry)

    # First reconciliation exposes safe status but never secret-presence metadata.
    events = bridge.reconcile("github", project_id=None, now=0)
    assert len(events) == 1
    assert events[0].kind is ConnectorEventKind.STATUS_CHANGED
    assert "auth_material_present" not in events[0].payload

    # Project-scoped remediation is visible only inside its owning project.
    scoped_events = bridge.reconcile("builder-provider", project_id="project-a", now=0)
    assert [event.kind for event in scoped_events] == [
        ConnectorEventKind.STATUS_CHANGED,
        ConnectorEventKind.REMEDIATION_OPENED,
    ]
    assert bridge.startup_banners(project_id="project-b", now=0) == ()
    banners_a = bridge.startup_banners(project_id="project-a", now=0)
    assert len(banners_a) == 1
    assert banners_a[0]["connector_id"] == "builder-provider"

    # Cursor reads cannot leak project-scoped events to another project.
    assert not any(
        event.connector_id == "builder-provider"
        for event in bridge.events_since(0, project_id="project-b")
    )
    assert any(
        event.connector_id == "builder-provider"
        for event in bridge.events_since(0, project_id="project-a")
    )

    # A global auth problem appears as a launch banner in project contexts.
    registry.update_health("github", project_id=None, health=ConnectorHealth.AUTH_INVALID)
    global_events = bridge.reconcile("github", project_id=None, now=10)
    assert [event.kind for event in global_events] == [
        ConnectorEventKind.STATUS_CHANGED,
        ConnectorEventKind.REMEDIATION_OPENED,
    ]
    assert any(
        banner["connector_id"] == "github"
        for banner in bridge.startup_banners(project_id="project-a", now=10)
    )

    # Temporary dismissal suppresses launch banners until its reminder time.
    registry.dismiss_notice("github", project_id=None, until=100)
    assert not any(
        banner["connector_id"] == "github"
        for banner in bridge.startup_banners(project_id=None, now=50)
    )
    assert any(
        banner["connector_id"] == "github"
        for banner in bridge.startup_banners(project_id=None, now=101)
    )

    # Resolving the underlying problem emits automatic remediation clearing.
    registry.update_health("github", project_id=None, health=ConnectorHealth.HEALTHY)
    cleared = bridge.reconcile("github", project_id=None, now=101)
    assert [event.kind for event in cleared] == [
        ConnectorEventKind.STATUS_CHANGED,
        ConnectorEventKind.REMEDIATION_CLEARED,
    ]
    assert not any(
        banner["connector_id"] == "github"
        for banner in bridge.startup_banners(project_id=None, now=101)
    )

    # Reconciliation is quiet when canonical state has not changed.
    assert bridge.reconcile("github", project_id=None, now=102) == ()

    # Checkpoints contain only replay/UI state and no credential material.
    checkpoint = bridge.checkpoint()
    text = repr(checkpoint).lower()
    for forbidden in ("token", "secret", "api_key", "auth_material_present"):
        assert forbidden not in text
    assert checkpoint["sequence"] >= 1

    print("CONNECTOR_EVENT_BRIDGE_SCOPED_PASS")


if __name__ == "__main__":
    main()
