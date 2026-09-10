"""Regression for explicit, secret-free connector action execution."""
from src.captain.connector_actions import ConnectResult, ConnectionTestResult, ConnectorActionService
from src.captain.connector_settings import (
    AuthMethod, ConnectorError, ConnectorHealth, ConnectorSetupSpec,
    ConnectorSettingsRegistry, ConnectorState,
)


def expect_error(fn) -> None:
    try:
        fn()
    except ConnectorError:
        return
    raise AssertionError("expected ConnectorError")


class FakeAdapter:
    def __init__(self, connect_result, test_result) -> None:
        self.connect_result, self.test_result = connect_result, test_result
        self.connect_calls = self.test_calls = 0
    def connect(self, *, project_id, credential_handle):
        self.connect_calls += 1
        return self.connect_result
    def test_connection(self, *, project_id):
        self.test_calls += 1
        return self.test_result


def state(connector_id, method, *, project_id=None, installed=True):
    return ConnectorState(connector_id, project_id, installed, False, False, method, health=ConnectorHealth.UNKNOWN)


def main() -> None:
    registry = ConnectorSettingsRegistry()
    registry.put(state("github", AuthMethod.OAUTH))
    oauth = FakeAdapter(
        ConnectResult(False, False, "https://github.com/login/oauth/authorize", {"flow": "official"}),
        ConnectionTestResult(True, ConnectorHealth.HEALTHY, "Connection healthy", "2.0", "oauth2"),
    )
    service = ConnectorActionService(registry)
    service.register(ConnectorSetupSpec("github", AuthMethod.OAUTH), oauth)

    expect_error(lambda: service.connect("github", project_id=None, user_initiated=False))
    expect_error(lambda: service.test_connection("github", project_id=None, user_initiated=False))
    assert oauth.connect_calls == oauth.test_calls == 0
    expect_error(lambda: service.connect("github", project_id=None, credential_handle="vault://manual", user_initiated=True))
    result = service.connect("github", project_id=None, user_initiated=True)
    assert result.authorization_url.startswith("https://")

    tested = service.test_connection("github", project_id=None, user_initiated=True)
    assert tested.ok
    github = registry.get("github", project_id=None)
    assert github.health is ConnectorHealth.HEALTHY
    assert github.version == "2.0" and github.provider_auth_version == "oauth2"
    assert not github.connected

    registry.put(state("custom", AuthMethod.API_KEY, project_id="project-a"))
    key_adapter = FakeAdapter(
        ConnectResult(True, True, safe_metadata={"provider": "custom"}),
        ConnectionTestResult(True, ConnectorHealth.HEALTHY, "Connection healthy"),
    )
    service.register(ConnectorSetupSpec("custom", AuthMethod.API_KEY, ("api_key",)), key_adapter)
    expect_error(lambda: service.connect("custom", project_id="project-a", user_initiated=True))
    # Raw keys, arbitrary strings, query/fragment-bearing refs and userinfo are rejected before the adapter runs.
    for unsafe in ("sk-live-raw-secret", "abc123", "vault://connector/custom?token=x", "vault://user@connector/custom", "vault://connector/custom#secret"):
        expect_error(lambda unsafe=unsafe: service.connect("custom", project_id="project-a", credential_handle=unsafe, user_initiated=True))
    assert key_adapter.connect_calls == 0
    service.connect("custom", project_id="project-a", credential_handle="vault://connector/custom", user_initiated=True)
    custom = registry.get("custom", project_id="project-a")
    assert custom.connected and custom.auth_material_present
    assert "vault" not in str(custom.safe_status()).lower()

    bad = FakeAdapter(
        ConnectResult(True, True, safe_metadata={"access_token": "x"}),
        ConnectionTestResult(True, ConnectorHealth.HEALTHY, "Connection healthy"),
    )
    registry.put(state("bad", AuthMethod.API_KEY))
    service.register(ConnectorSetupSpec("bad", AuthMethod.API_KEY, ("api_key",)), bad)
    expect_error(lambda: service.connect("bad", project_id=None, credential_handle="vault://bad", user_initiated=True))

    bad_test = FakeAdapter(ConnectResult(False, False), ConnectionTestResult(False, ConnectorHealth.AUTH_INVALID, "token expired"))
    registry.put(state("bad-test", AuthMethod.LOCAL))
    service.register(ConnectorSetupSpec("bad-test", AuthMethod.LOCAL), bad_test)
    expect_error(lambda: service.test_connection("bad-test", project_id=None, user_initiated=True))

    expect_error(lambda: service.register(ConnectorSetupSpec("github", AuthMethod.OAUTH), oauth))
    registry.put(state("drift", AuthMethod.LOCAL))
    drift = FakeAdapter(ConnectResult(False, False), ConnectionTestResult(True, ConnectorHealth.HEALTHY, "Healthy"))
    service.register(ConnectorSetupSpec("drift", AuthMethod.OAUTH), drift)
    expect_error(lambda: service.test_connection("drift", project_id=None, user_initiated=True))
    print("CONNECTOR_ACTION_RUNTIME_HARDENED_PASS")


if __name__ == "__main__":
    main()
