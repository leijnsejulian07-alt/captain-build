"""Regression: provider-granted permissions are authoritative after Connect."""
from dataclasses import replace

from src.captain.connector_actions import ConnectResult, ConnectionTestResult, ConnectorActionService
from src.captain.connector_settings import (
    AuthMethod,
    ConnectorError,
    ConnectorHealth,
    ConnectorSetupSpec,
    ConnectorSettingsRegistry,
    ConnectorState,
)


class Adapter:
    def __init__(self, result: ConnectResult) -> None:
        self.result = result

    def connect(self, *, project_id, credential_handle):
        return self.result

    def test_connection(self, *, project_id):
        return ConnectionTestResult(True, ConnectorHealth.HEALTHY, "Healthy")


def expect_error(fn) -> None:
    try:
        fn()
    except ConnectorError:
        return
    raise AssertionError("expected ConnectorError")


def base_state(connector_id: str, *, permissions=frozenset()) -> ConnectorState:
    return ConnectorState(
        connector_id=connector_id,
        project_id=None,
        installed=True,
        connected=False,
        enabled=True,
        auth_method=AuthMethod.OAUTH,
        permissions=permissions,
        required_permissions=frozenset({"repo:read", "issues:write"}),
        health=ConnectorHealth.HEALTHY,
    )


def main() -> None:
    registry = ConnectorSettingsRegistry()
    registry.put(base_state("github", permissions=frozenset({"stale:admin"})))
    service = ConnectorActionService(registry)
    service.register(
        ConnectorSetupSpec("github", AuthMethod.OAUTH),
        Adapter(ConnectResult(True, True, granted_permissions=("repo:read", "issues:write"))),
    )
    service.connect("github", project_id=None, user_initiated=True)
    state = registry.get("github", project_id=None)
    assert state is not None
    assert state.permissions == frozenset({"repo:read", "issues:write"})
    assert "stale:admin" not in state.permissions
    assert state.ready

    # A reconnect that reports no grants must clear old grants rather than inheriting them.
    registry.put(replace(state, connected=False, auth_material_present=False))
    service2 = ConnectorActionService(registry)
    service2.register(
        ConnectorSetupSpec("github", AuthMethod.OAUTH),
        Adapter(ConnectResult(True, True)),
    )
    service2.connect("github", project_id=None, user_initiated=True)
    state = registry.get("github", project_id=None)
    assert state is not None and not state.permissions and not state.ready

    # Malformed, duplicate, whitespace-padded, or sensitive-looking scope names fail closed.
    for index, grants in enumerate((
        ("repo:read", "repo:read"),
        (" repo:read",),
        ("",),
        ("access_token:read",),
    )):
        connector_id = f"bad-{index}"
        registry.put(replace(base_state(connector_id), enabled=False))
        bad_service = ConnectorActionService(registry)
        bad_service.register(
            ConnectorSetupSpec(connector_id, AuthMethod.OAUTH),
            Adapter(ConnectResult(True, True, granted_permissions=grants)),
        )
        expect_error(lambda bad_service=bad_service, connector_id=connector_id: bad_service.connect(connector_id, project_id=None, user_initiated=True))
        bad_state = registry.get(connector_id, project_id=None)
        assert bad_state is not None and not bad_state.connected

    print("CONNECTOR_GRANTED_PERMISSIONS_FAIL_CLOSED_PASS")


if __name__ == "__main__":
    main()
