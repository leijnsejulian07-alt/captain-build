from connector_runtime_state import AuthMethod, ConnectorRuntimeState


def state(**overrides):
    values = dict(
        connector_id="github",
        installed=True,
        connected=True,
        enabled=True,
        ready=True,
        auth_method=AuthMethod.OAUTH,
        permissions=frozenset({"repo:read"}),
        health="healthy",
        remediation_code=None,
    )
    values.update(overrides)
    return ConnectorRuntimeState(**values)


def expect_invalid(**overrides):
    try:
        state(**overrides).validate()
    except ValueError:
        return
    raise AssertionError(f"expected invalid state: {overrides}")


def run():
    healthy = state().validate()
    assert healthy.may_execute is True
    assert "token" not in repr(healthy.public_status()).lower()
    assert "secret" not in repr(healthy.public_status()).lower()

    for field in ("installed", "connected", "enabled", "ready"):
        broken = state(**{field: False})
        if field in {"installed", "connected", "enabled"}:
            expect_invalid(**{field: False})
        else:
            expect_invalid(ready=False, health="healthy")
        assert broken.may_execute is False

    for health in ("invalid_credentials", "expired", "deprecated_auth", "migration_required"):
        expect_invalid(health=health, remediation_code=None)
        blocked = state(ready=False, health=health, remediation_code=f"fix:{health}")
        assert blocked.validate().may_execute is False

    expect_invalid(connected=True, installed=False)
    expect_invalid(enabled=True, installed=False)
    expect_invalid(ready=True, enabled=False)
    expect_invalid(connector_id="bad id")


if __name__ == "__main__":
    run()
    print("connector runtime regressions: PASS")
