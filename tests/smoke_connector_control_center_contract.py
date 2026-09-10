"""Regression coverage for Captain's canonical connector Control Center coordinator."""
from dataclasses import replace

from src.captain.connector_actions import (
    ConnectResult,
    ConnectionTestResult,
    ConnectorActionService,
)
from src.captain.connector_control_center import ConnectorControlCenter
from src.captain.connector_event_bridge import ConnectorEventBridge
from src.captain.connector_settings import (
    AuthMethod,
    ConnectorError,
    ConnectorHealth,
    ConnectorSettingsRegistry,
    ConnectorSetupSpec,
    ConnectorState,
)


class LocalAdapter:
    def connect(self, *, project_id, credential_handle):
        assert credential_handle is None
        return ConnectResult(connected=True, auth_material_present=False, safe_metadata={"mode": "local"})

    def test_connection(self, *, project_id):
        return ConnectionTestResult(
            ok=True,
            health=ConnectorHealth.HEALTHY,
            safe_message="Local provider reachable",
            provider_version="1.2.3",
            safe_metadata={"transport": "local"},
        )


def expect_error(fn, text):
    try:
        fn()
    except ConnectorError as exc:
        assert text in str(exc)
    else:
        raise AssertionError(f"expected ConnectorError containing {text!r}")


def build():
    registry = ConnectorSettingsRegistry()
    actions = ConnectorActionService(registry)
    actions.register(ConnectorSetupSpec("local-tools", AuthMethod.LOCAL), LocalAdapter())
    actions.register(ConnectorSetupSpec("paid-local", AuthMethod.LOCAL), LocalAdapter())

    registry.put(ConnectorState(
        connector_id="local-tools", project_id=None, installed=True, connected=True,
        enabled=True, auth_method=AuthMethod.LOCAL, health=ConnectorHealth.HEALTHY,
    ))
    registry.put(ConnectorState(
        connector_id="local-tools", project_id="project-a", installed=True, connected=True,
        enabled=True, auth_method=AuthMethod.LOCAL, health=ConnectorHealth.DEGRADED,
    ))
    registry.put(ConnectorState(
        connector_id="local-tools", project_id="project-b", installed=True, connected=True,
        enabled=True, auth_method=AuthMethod.LOCAL, health=ConnectorHealth.HEALTHY,
    ))
    registry.put(ConnectorState(
        connector_id="paid-local", project_id="project-a", installed=True, connected=True,
        enabled=False, auth_method=AuthMethod.LOCAL, health=ConnectorHealth.HEALTHY,
        paid_service=True,
    ))
    bridge = ConnectorEventBridge(registry)
    return registry, ConnectorControlCenter(registry, actions, bridge)


def test_scoped_startup_surface_and_banners():
    _, control = build()
    snap = control.snapshot(project_id="project-a", now=100.0)
    payload = snap.safe_payload()
    scopes = {(row["connector_id"], row["project_id"]) for row in payload["rows"]}
    assert ("local-tools", None) in scopes
    assert ("local-tools", "project-a") in scopes
    assert ("paid-local", "project-a") in scopes
    assert ("local-tools", "project-b") not in scopes
    assert any(b["connector_id"] == "local-tools" and b["project_id"] == "project-a" for b in payload["banners"])
    assert all(b["project_id"] in {None, "project-a"} for b in payload["banners"])


def test_all_mutations_require_explicit_user_action():
    _, control = build()
    expect_error(
        lambda: control.perform("local-tools", "disable", project_id="project-a", now=100.0, user_initiated=False),
        "explicit user action",
    )
    expect_error(
        lambda: control.perform("local-tools", "open_remediation", project_id="project-a", now=100.0, user_initiated=True),
        "non-executable",
    )


def test_paid_activation_requires_specific_approved_path():
    registry, control = build()
    expect_error(
        lambda: control.perform("paid-local", "enable", project_id="project-a", now=100.0, user_initiated=True),
        "enable_with_approval",
    )
    expect_error(
        lambda: control.perform("paid-local", "enable_with_approval", project_id="project-a", now=100.0, user_initiated=True),
        "explicit approval",
    )
    result = control.perform(
        "paid-local", "enable_with_approval", project_id="project-a", now=100.0,
        user_initiated=True, paid_activation_approved=True,
    )
    assert registry.get("paid-local", project_id="project-a").enabled is True
    assert any(r.connector_id == "paid-local" and r.enabled for r in result.snapshot.rows)


def test_remediation_dismissal_reappears_and_then_auto_clears_after_recovery():
    registry, control = build()
    first = control.snapshot(project_id="project-a", now=100.0)
    assert any(b["connector_id"] == "local-tools" for b in first.banners)

    dismissed = control.perform(
        "local-tools", "dismiss_remediation", project_id="project-a", now=100.0,
        user_initiated=True, dismiss_until=200.0,
    )
    assert not any(b["connector_id"] == "local-tools" and b["project_id"] == "project-a" for b in dismissed.snapshot.banners)

    reminded = control.snapshot(project_id="project-a", now=201.0)
    assert any(b["connector_id"] == "local-tools" and b["project_id"] == "project-a" for b in reminded.banners)

    registry.update_health("local-tools", project_id="project-a", health=ConnectorHealth.HEALTHY)
    recovered = control.snapshot(project_id="project-a", now=202.0)
    assert not any(b["connector_id"] == "local-tools" and b["project_id"] == "project-a" for b in recovered.banners)


def test_snapshot_and_events_are_secret_free():
    _, control = build()
    result = control.perform(
        "local-tools", "test_connection", project_id="project-a", now=100.0, user_initiated=True,
    )
    rendered = repr(result.snapshot.safe_payload()).lower() + repr(result.events).lower()
    for forbidden in ("password", "api_key", "apikey", "authorization", "credential_handle"):
        assert forbidden not in rendered
    assert result.test_result.ok is True


if __name__ == "__main__":
    test_scoped_startup_surface_and_banners()
    test_all_mutations_require_explicit_user_action()
    test_paid_activation_requires_specific_approved_path()
    test_remediation_dismissal_reappears_and_then_auto_clears_after_recovery()
    test_snapshot_and_events_are_secret_free()
    print("CONNECTOR_CONTROL_CENTER_RUNTIME_PASS")
