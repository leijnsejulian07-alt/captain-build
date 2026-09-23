from connector_notice_store import ConnectorNoticeStore


def test_notice_is_scoped_snoozable_and_resurfaces():
    store = ConnectorNoticeStore(reminder_seconds=100)
    store.reconcile("project-a", "github", ("auth_expired",), now=10)
    assert store.visible("project-a", 10) == ({
        "connector_id": "github", "code": "auth_expired",
        "settings_deep_link": "settings://connectors/github"},)
    assert store.visible("project-b", 10) == ()
    assert store.dismiss_temporarily("project-a", "github", "auth_expired", 20)
    assert store.visible("project-a", 50) == ()
    assert store.visible("project-a", 50, launch=True)
    assert store.visible("project-a", 120)


def test_resolution_clears_notice_automatically():
    store = ConnectorNoticeStore()
    store.reconcile("global", "github", ("provider_deprecated",), now=1)
    assert store.visible("global", 1)
    store.reconcile("global", "github", (), now=2)
    assert store.visible("global", 2) == ()


def test_reconcile_one_connector_does_not_touch_other_scope_or_connector():
    store = ConnectorNoticeStore()
    store.reconcile("a", "github", ("auth_expired",), now=1)
    store.reconcile("a", "drive", ("setup_changed",), now=1)
    store.reconcile("b", "github", ("provider_deprecated",), now=1)
    store.reconcile("a", "github", (), now=2)
    assert {x["connector_id"] for x in store.visible("a", 2)} == {"drive"}
    assert store.visible("b", 2)[0]["code"] == "provider_deprecated"


def test_output_never_contains_provider_diagnostics_or_secrets():
    store = ConnectorNoticeStore()
    store.reconcile("a", "x", ("auth_expired",), now=1)
    rendered = repr(store.visible("a", 1)).lower()
    assert "token" not in rendered and "secret" not in rendered and "raw_error" not in rendered


def test_non_plain_active_codes_fail_closed():
    store = ConnectorNoticeStore()
    try:
        store.reconcile("a", "x", ["auth_expired"], now=1)
    except TypeError:
        pass
    else:
        raise AssertionError("mutable/untrusted active code container accepted")
