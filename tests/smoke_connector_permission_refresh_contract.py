"""Regression: Test Connection can authoritatively refresh provider permissions."""
from dataclasses import replace

from src.captain.connector_actions import ConnectResult, ConnectionTestResult, ConnectorActionService
from src.captain.connector_settings import (
    AuthMethod,
    ConnectorError,
    ConnectorHealth,
    ConnectorSetupSpec,
    ConnectorSettingsRegistry,
    ConnectorState,
    remediation_reason,
)


class Adapter:
    def __init__(self, test_result: ConnectionTestResult) -> None:
        self.test_result = test_result

    def connect(self, *, project_id, credential_handle):
        return ConnectResult(True, True, granted_permissions=("repo:read", "issues:write"))

    def test_connection(self, *, project_id):
        return self.test_result


def expect_error(fn) -> None:
    try:
        fn()
    except ConnectorError:
        return
    raise AssertionError("expected ConnectorError")


def state(connector_id: str = "github") -> ConnectorState:
    return ConnectorState(
        connector_id=connector_id,
        project_id=None,
        installed=True,
        connected=True,
        enabled=True,
        auth_method=AuthMethod.OAUTH,
        permissions=frozenset({"repo:read", "issues:write"}),
        required_permissions=frozenset({"repo:read", "issues:write"}),
        health=ConnectorHealth.HEALTHY,
        auth_material_present=True,
    )


def service_for(registry, connector_id, result):
    service = ConnectorActionService(registry)
    service.register(ConnectorSetupSpec(connector_id, AuthMethod.OAUTH), Adapter(result))
    return service


def main() -> None:
    registry = ConnectorSettingsRegistry()
    registry.put(state())

    # Provider-side scope revocation replaces stale grants and makes Ready fail closed.
    service = service_for(
        registry,
        "github",
        ConnectionTestResult(
            True,
            ConnectorHealth.HEALTHY,
            "Healthy",
            permissions_authoritative=True,
            granted_permissions=("repo:read",),
        ),
    )
    service.test_connection("github", project_id=None, user_initiated=True)
    current = registry.get("github", project_id=None)
    assert current is not None
    assert current.permissions == frozenset({"repo:read"})
    assert not current.ready
    assert remediation_reason(current) == "Required permissions are missing"

    # An authoritative empty observation revokes all previously granted scopes.
    registry.put(replace(current, permissions=frozenset({"repo:read", "issues:write"})))
    empty = service_for(
        registry,
        "github",
        ConnectionTestResult(
            True,
            ConnectorHealth.HEALTHY,
            "Healthy",
            permissions_authoritative=True,
            granted_permissions=(),
        ),
    )
    empty.test_connection("github", project_id=None, user_initiated=True)
    current = registry.get("github", project_id=None)
    assert current is not None and not current.permissions and not current.ready

    # Providers that cannot attest scopes must not silently alter existing permissions.
    registry.put(replace(current, permissions=frozenset({"repo:read", "issues:write"})))
    opaque = service_for(
        registry,
        "github",
        ConnectionTestResult(True, ConnectorHealth.HEALTHY, "Healthy"),
    )
    opaque.test_connection("github", project_id=None, user_initiated=True)
    current = registry.get("github", project_id=None)
    assert current is not None
    assert current.permissions == frozenset({"repo:read", "issues:write"})

    # A provider may not return scopes while claiming they are non-authoritative.
    registry.put(state("bad"))
    bad = service_for(
        registry,
        "bad",
        ConnectionTestResult(
            True,
            ConnectorHealth.HEALTHY,
            "Healthy",
            granted_permissions=("repo:read",),
        ),
    )
    expect_error(lambda: bad.test_connection("bad", project_id=None, user_initiated=True))
    unchanged = registry.get("bad", project_id=None)
    assert unchanged is not None
    assert unchanged.permissions == frozenset({"repo:read", "issues:write"})

    print("CONNECTOR_PERMISSION_REFRESH_FAIL_CLOSED_PASS")


if __name__ == "__main__":
    main()