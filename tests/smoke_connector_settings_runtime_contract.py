"""Runtime regression for canonical Captain connector/settings state."""

from src.captain.connector_settings import (
    AuthMethod,
    ConnectorError,
    ConnectorHealth,
    ConnectorSetupSpec,
    ConnectorSettingsRegistry,
    ConnectorState,
)


def expect_error(fn) -> None:
    try:
        fn()
    except ConnectorError:
        return
    raise AssertionError("expected ConnectorError")


def main() -> None:
    # OAuth must use the official Connect flow rather than manual secret fields.
    ConnectorSetupSpec("github", AuthMethod.OAUTH).validate()
    expect_error(lambda: ConnectorSetupSpec("github", AuthMethod.OAUTH, ("token",)).validate())
    ConnectorSetupSpec("custom", AuthMethod.API_KEY, ("api_key",)).validate()

    registry = ConnectorSettingsRegistry()
    healthy = ConnectorState(
        connector_id="github",
        project_id=None,
        installed=True,
        connected=True,
        enabled=True,
        auth_method=AuthMethod.OAUTH,
        permissions=frozenset({"repo:read", "repo:write"}),
        required_permissions=frozenset({"repo:read"}),
        health=ConnectorHealth.HEALTHY,
        version="1.2.3",
        auth_material_present=True,
        provider_auth_version="oauth2",
    )
    registry.put(healthy)
    assert healthy.ready
    assert healthy.safe_status()["ready"] is True
    assert "auth_material_present" not in healthy.safe_status()
    assert registry.visible_notices(project_id=None, now=0) == ()

    # Installed, Connected, Enabled and Ready are independent lifecycle states.
    disconnected = ConnectorState(
        "drive", None, True, False, False, AuthMethod.OAUTH,
        health=ConnectorHealth.UNKNOWN,
    )
    registry.put(disconnected)
    assert not disconnected.ready
    enabled_disconnected = ConnectorState(
        "calendar", None, True, False, True, AuthMethod.OAUTH,
        health=ConnectorHealth.UNKNOWN,
    )
    registry.put(enabled_disconnected)
    assert not enabled_disconnected.ready
    assert registry.visible_notices(project_id=None, now=0)

    # Paid services may never become enabled without explicit approval.
    paid = ConnectorState(
        "paid", None, True, True, False, AuthMethod.API_KEY,
        auth_material_present=True, health=ConnectorHealth.HEALTHY,
        paid_service=True,
    )
    registry.put(paid)
    expect_error(lambda: registry.set_enabled("paid", project_id=None, enabled=True))
    approved = registry.set_enabled(
        "paid", project_id=None, enabled=True, paid_activation_approved=True
    )
    assert approved.ready

    # Health/auth migration problems become persistent safe remediation notices.
    registry.update_health(
        "github", project_id=None,
        health=ConnectorHealth.MIGRATION_REQUIRED,
        provider_auth_version="oauth3-required",
    )
    notices = registry.visible_notices(project_id=None, now=100)
    github_notice = next(n for n in notices if n.connector_id == "github")
    assert set(github_notice.safe_payload()) == {
        "connector_id", "project_id", "reason", "settings_deep_link"
    }
    assert github_notice.settings_deep_link == "settings://connectors/github"

    # Temporary dismissal hides but does not resolve the notice; it reappears later.
    registry.dismiss_notice("github", project_id=None, until=200)
    assert not any(
        n.connector_id == "github"
        for n in registry.visible_notices(project_id=None, now=150)
    )
    assert any(
        n.connector_id == "github"
        for n in registry.visible_notices(project_id=None, now=201)
    )

    # Fixing the underlying connector automatically clears its notice.
    registry.update_health(
        "github", project_id=None,
        health=ConnectorHealth.HEALTHY,
        provider_auth_version="oauth3",
    )
    assert not any(
        n.connector_id == "github"
        for n in registry.visible_notices(project_id=None, now=1000)
    )

    # Project-scoped notices cannot leak into another project.
    scoped = ConnectorState(
        "repo-tool", "project-a", True, True, True, AuthMethod.OAUTH,
        permissions=frozenset(), required_permissions=frozenset({"repo:read"}),
        auth_material_present=True, health=ConnectorHealth.HEALTHY,
    )
    registry.put(scoped)
    assert any(
        n.connector_id == "repo-tool"
        for n in registry.visible_notices(project_id="project-a", now=0)
    )
    assert not any(
        n.connector_id == "repo-tool"
        for n in registry.visible_notices(project_id="project-b", now=0)
    )

    # Global connector notices remain visible from a project, by design.
    registry.update_health("calendar", project_id=None, health=ConnectorHealth.DEGRADED)
    assert any(
        n.connector_id == "calendar"
        for n in registry.visible_notices(project_id="project-a", now=0)
    )

    # Malformed/unsafe lifecycle combinations fail closed.
    expect_error(lambda: registry.put(ConnectorState(
        "bad", None, False, True, False, AuthMethod.API_KEY,
        auth_material_present=True,
    )))
    expect_error(lambda: registry.put(ConnectorState(
        "bad2", None, True, True, False, AuthMethod.API_KEY,
        auth_material_present=False,
    )))

    print("CONNECTOR_SETTINGS_RUNTIME_HARDENED_PASS")


if __name__ == "__main__":
    main()
