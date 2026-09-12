import pytest

from connector_connect_test_flow import (
    ConnectAction,
    ConnectionTestResult,
    ConnectorSetupSpec,
    apply_test_result,
)
from connector_runtime_state import AuthMethod, ConnectorRuntimeState


def base_state(*, auth=AuthMethod.OAUTH, enabled=True):
    return ConnectorRuntimeState(
        connector_id="github",
        installed=True,
        connected=False,
        enabled=enabled,
        ready=False,
        auth_method=auth,
        health="unknown",
    )


def test_oauth_requires_official_https_flow_and_no_manual_secret_fields():
    spec = ConnectorSetupSpec(
        connector_id="github",
        auth_method=AuthMethod.OAUTH,
        oauth_authorize_url="https://github.com/login/oauth/authorize",
        requested_permissions=frozenset({"repo:read"}),
    )
    assert spec.connect_action is ConnectAction.OFFICIAL_OAUTH
    assert spec.public_setup()["test_connection_available"] is True
    with pytest.raises(ValueError):
        ConnectorSetupSpec(
            connector_id="github",
            auth_method=AuthMethod.OAUTH,
            oauth_authorize_url="http://example.test/oauth",
        ).validate()
    with pytest.raises(ValueError):
        ConnectorSetupSpec(
            connector_id="github",
            auth_method=AuthMethod.OAUTH,
            oauth_authorize_url="https://github.com/login/oauth/authorize",
            required_fields=("token",),
        ).validate()


def test_api_key_and_id_setup_are_explicit_not_invented():
    api = ConnectorSetupSpec(
        connector_id="search",
        auth_method=AuthMethod.API_KEY,
        required_fields=("api_key",),
    )
    assert api.connect_action is ConnectAction.ENTER_API_KEY
    with pytest.raises(ValueError):
        ConnectorSetupSpec(
            connector_id="search",
            auth_method=AuthMethod.API_KEY,
            required_fields=("username", "password"),
        ).validate()

    ident = ConnectorSetupSpec(
        connector_id="workspace",
        auth_method=AuthMethod.ID,
        required_fields=("workspace_id",),
    )
    assert ident.connect_action is ConnectAction.ENTER_ID


def test_successful_test_can_make_enabled_connector_ready_without_permission_escalation():
    spec = ConnectorSetupSpec(
        connector_id="github",
        auth_method=AuthMethod.OAUTH,
        oauth_authorize_url="https://github.com/login/oauth/authorize",
        requested_permissions=frozenset({"repo:read", "issues:read"}),
    )
    result = ConnectionTestResult(
        connector_id="github",
        ok=True,
        health="healthy",
        granted_permissions=frozenset({"repo:read"}),
    )
    state = apply_test_result(current=base_state(enabled=True), spec=spec, result=result)
    assert state.connected and state.enabled and state.ready and state.may_execute
    assert state.permissions == frozenset({"repo:read"})

    escalated = ConnectionTestResult(
        connector_id="github",
        ok=True,
        health="healthy",
        granted_permissions=frozenset({"admin:all"}),
    )
    with pytest.raises(ValueError):
        apply_test_result(current=base_state(enabled=True), spec=spec, result=escalated)


def test_success_does_not_silently_enable_disabled_connector():
    spec = ConnectorSetupSpec(
        connector_id="github",
        auth_method=AuthMethod.OAUTH,
        oauth_authorize_url="https://github.com/login/oauth/authorize",
    )
    result = ConnectionTestResult(connector_id="github", ok=True, health="healthy")
    state = apply_test_result(current=base_state(enabled=False), spec=spec, result=result)
    assert state.connected is True
    assert state.enabled is False
    assert state.ready is False
    assert state.health == "unknown"
    assert state.may_execute is False


def test_explicit_enable_after_success_is_allowed_but_never_implicit():
    spec = ConnectorSetupSpec(
        connector_id="github",
        auth_method=AuthMethod.OAUTH,
        oauth_authorize_url="https://github.com/login/oauth/authorize",
    )
    result = ConnectionTestResult(connector_id="github", ok=True, health="healthy")
    state = apply_test_result(current=base_state(enabled=False), spec=spec, result=result, enabled=True)
    assert state.ready and state.may_execute


def test_failed_auth_test_disconnects_and_surfaces_stable_remediation():
    spec = ConnectorSetupSpec(
        connector_id="github",
        auth_method=AuthMethod.OAUTH,
        oauth_authorize_url="https://github.com/login/oauth/authorize",
    )
    result = ConnectionTestResult(
        connector_id="github",
        ok=False,
        health="expired",
        remediation_code="reconnect_oauth",
    )
    state = apply_test_result(current=base_state(enabled=True), spec=spec, result=result)
    assert state.connected is False
    assert state.ready is False
    assert state.may_execute is False
    assert state.remediation_code == "reconnect_oauth"


def test_cross_connector_and_auth_method_mismatch_fail_closed():
    spec = ConnectorSetupSpec(
        connector_id="github",
        auth_method=AuthMethod.OAUTH,
        oauth_authorize_url="https://github.com/login/oauth/authorize",
    )
    foreign = ConnectionTestResult(connector_id="slack", ok=True, health="healthy")
    with pytest.raises(ValueError):
        apply_test_result(current=base_state(), spec=spec, result=foreign)

    wrong_auth = ConnectorSetupSpec(
        connector_id="github",
        auth_method=AuthMethod.API_KEY,
        required_fields=("api_key",),
    )
    ok = ConnectionTestResult(connector_id="github", ok=True, health="healthy")
    with pytest.raises(ValueError):
        apply_test_result(current=base_state(auth=AuthMethod.OAUTH), spec=wrong_auth, result=ok)


def test_test_result_rejects_secret_like_remediation_and_inconsistent_health():
    with pytest.raises(ValueError):
        ConnectionTestResult(
            connector_id="github",
            ok=False,
            health="invalid_credentials",
            remediation_code="token=abc123",
        ).validate()
    with pytest.raises(ValueError):
        ConnectionTestResult(connector_id="github", ok=True, health="expired").validate()
    with pytest.raises(ValueError):
        ConnectionTestResult(connector_id="github", ok=False, health="healthy").validate()
