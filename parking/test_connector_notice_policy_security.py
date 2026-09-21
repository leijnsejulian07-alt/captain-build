"""Security regressions for Captain connector notice persistence.

Parking test: reconcile with the real Settings/notification registry when a local
Captain runtime is reachable. Uses stdlib only and must not contain real secrets.
"""
from connector_notice_policy import build_notice, should_surface


def _state(**overrides):
    state = {
        "connector_id": "github",
        "installed": True,
        "connected": False,
        "enabled": True,
        "ready": False,
        "permissions": [],
        "auth_health": "expired",
        "provider_health": "ok",
        "remediation": {
            "code": "reauth_required",
            "safe_message": "Reconnect this connector in Settings.",
            "settings_path": "/settings/connectors/github",
        },
    }
    state.update(overrides)
    return state


def test_notice_is_allowlist_only_and_drops_unknown_secret_fields():
    state = _state(
        access_token="FAKE_TOKEN_MUST_NOT_PERSIST",
        api_key="FAKE_KEY_MUST_NOT_PERSIST",
        refresh_token="FAKE_REFRESH_MUST_NOT_PERSIST",
        headers={"Authorization": "Bearer FAKE"},
    )
    notice = build_notice(state, now_ts=1_000)
    blob = repr(notice)
    for forbidden in ("FAKE_TOKEN", "FAKE_KEY", "FAKE_REFRESH", "Authorization"):
        assert forbidden not in blob


def test_provider_message_cannot_override_safe_copy():
    state = _state(provider_message="token=FAKE_PROVIDER_SECRET")
    notice = build_notice(state, now_ts=1_000)
    assert "FAKE_PROVIDER_SECRET" not in repr(notice)


def test_deeplink_must_stay_inside_connector_settings():
    state = _state()
    state["remediation"] = dict(state["remediation"])
    state["remediation"]["settings_path"] = "https://evil.example/steal"
    notice = build_notice(state, now_ts=1_000)
    assert notice.get("settings_path", "").startswith("/settings/connectors/")


def test_unresolved_important_notice_resurfaces_after_reminder_window():
    notice = build_notice(_state(), now_ts=1_000)
    dismissed = dict(notice)
    dismissed["dismissed_until_ts"] = 1_000 + 86_400
    assert not should_surface(dismissed, now_ts=1_000 + 60)
    assert should_surface(dismissed, now_ts=1_000 + 86_401)


def test_ready_connector_does_not_create_problem_notice():
    state = _state(connected=True, ready=True, auth_health="ok")
    state["remediation"] = None
    assert build_notice(state, now_ts=1_000) is None


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"ok: {len(tests)} connector notice security regressions")
