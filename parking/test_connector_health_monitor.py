from connector_health_monitor import evaluate


def test_auth_migration_is_persistent_worthy_and_secret_free():
    old = {"connector_id": "github", "auth_method": "api_key"}
    cur = {"connector_id": "github", "auth_method": "oauth", "health": {
        "auth_status": "valid", "provider_version_status": "current"}}
    result = evaluate(old, cur)
    assert result["events"] == ("auth_method_migration",)
    assert result["important"] is True
    assert result["settings_deep_link"] == "settings://connectors/github"
    assert "token" not in repr(result).lower()


def test_expired_and_deprecated_are_detected_without_raw_diagnostics():
    cur = {"connector_id": "x", "auth_method": "oauth", "health": {
        "auth_status": "expired", "provider_version_status": "deprecated",
        "raw_error": "secret=DO_NOT_LEAK"}}
    result = evaluate(None, cur)
    assert result["events"] == ("auth_expired", "provider_deprecated")
    assert "DO_NOT_LEAK" not in repr(result)


def test_setup_change_and_malformed_auth_fail_closed():
    cur = {"connector_id": "x", "auth_method": "mystery", "health": {
        "setup_status": "changed"}}
    result = evaluate(None, cur)
    assert result["events"] == ("setup_changed",)
    assert result["important"] is True


def test_custom_mapping_is_rejected_before_iteration():
    touched = {"value": False}
    class Hostile(dict):
        def get(self, *args, **kwargs):
            touched["value"] = True
            raise AssertionError("hook executed")
    try:
        evaluate(None, Hostile(connector_id="x"))
    except TypeError:
        pass
    else:
        raise AssertionError("hostile mapping accepted")
    assert touched["value"] is False
