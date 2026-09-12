from datetime import datetime, timedelta, timezone

import pytest

from connector_remediation_notices import ConnectorNoticeStore
from connector_runtime_state import AuthMethod, ConnectorRuntimeState


NOW = datetime(2026, 9, 12, 6, 0, tzinfo=timezone.utc)


def state(*, health: str, remediation: str | None, ready: bool = False) -> ConnectorRuntimeState:
    return ConnectorRuntimeState(
        connector_id="github",
        installed=True,
        connected=ready,
        enabled=True,
        ready=ready,
        auth_method=AuthMethod.OAUTH,
        permissions=frozenset({"repo:read"}),
        health=health,
        remediation_code=remediation,
    )


def test_unresolved_notice_survives_relaunch_and_reappears_after_dismissal() -> None:
    store = ConnectorNoticeStore(scope_id="settings:user", reminder_interval=timedelta(hours=24))
    store.reconcile([state(health="expired", remediation="oauth_reconnect")], now=NOW)
    assert store.visible(now=NOW)[0]["deep_link"] == "captain://settings/connectors/github"

    store.dismiss_temporarily("github", now=NOW)
    assert store.visible(now=NOW + timedelta(hours=23)) == []

    restored = ConnectorNoticeStore.from_persisted_records(
        scope_id="settings:user",
        records=store.persisted_records(),
        reminder_interval=timedelta(hours=24),
    )
    assert restored.visible(now=NOW + timedelta(hours=25))[0]["remediation_code"] == "oauth_reconnect"


def test_resolution_auto_clears_notice() -> None:
    store = ConnectorNoticeStore(scope_id="settings:user")
    store.reconcile([state(health="expired", remediation="oauth_reconnect")], now=NOW)
    assert store.persisted_records()

    healthy = state(health="healthy", remediation=None, ready=True)
    store.reconcile([healthy], now=NOW + timedelta(minutes=1))
    assert store.persisted_records() == []
    assert store.visible(now=NOW + timedelta(minutes=1)) == []


def test_partial_poll_does_not_silently_clear_unobserved_problem() -> None:
    store = ConnectorNoticeStore(scope_id="settings:user")
    store.reconcile([state(health="expired", remediation="oauth_reconnect")], now=NOW)
    store.reconcile([], now=NOW + timedelta(minutes=5))
    assert len(store.persisted_records()) == 1


def test_cross_scope_persisted_notice_is_rejected() -> None:
    store = ConnectorNoticeStore(scope_id="settings:user")
    store.reconcile([state(health="expired", remediation="oauth_reconnect")], now=NOW)
    records = store.persisted_records()
    with pytest.raises(ValueError, match="cross-scope"):
        ConnectorNoticeStore.from_persisted_records(scope_id="settings:other", records=records)


def test_public_projection_and_persistence_never_include_credentials() -> None:
    store = ConnectorNoticeStore(scope_id="settings:user")
    store.reconcile([state(health="invalid_credentials", remediation="reconnect_required")], now=NOW)
    combined = repr(store.visible(now=NOW)) + repr(store.persisted_records())
    assert "token" not in combined.lower()
    assert "password" not in combined.lower()
    assert "credential" not in combined.lower()


def test_secret_like_remediation_code_is_rejected() -> None:
    store = ConnectorNoticeStore(scope_id="settings:user")
    with pytest.raises(ValueError, match="secret-like"):
        store.reconcile([state(health="expired", remediation="token=abc123")], now=NOW)


def test_invalid_or_naive_timestamps_are_rejected() -> None:
    store = ConnectorNoticeStore(scope_id="settings:user")
    with pytest.raises(ValueError, match="timezone-aware"):
        store.reconcile([state(health="expired", remediation="oauth_reconnect")], now=datetime(2026, 9, 12, 6, 0))


def test_disabled_connector_with_remediation_also_gets_notice() -> None:
    disabled = ConnectorRuntimeState(
        connector_id="github",
        installed=True,
        connected=True,
        enabled=False,
        ready=False,
        auth_method=AuthMethod.OAUTH,
        health="unknown",
        remediation_code="enable_connector",
    )
    store = ConnectorNoticeStore(scope_id="settings:user")
    store.reconcile([disabled], now=NOW)
    assert store.visible(now=NOW)[0]["remediation_code"] == "enable_connector"
