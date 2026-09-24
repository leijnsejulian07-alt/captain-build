"""Dependency-free regressions for connector health/settings trust boundary."""
from connector_health_monitor import evaluate


class HostileStr(str):
    def __hash__(self):
        raise AssertionError("hostile __hash__ executed")
    def __eq__(self, other):
        raise AssertionError("hostile __eq__ executed")
    def strip(self, *args, **kwargs):
        raise AssertionError("hostile strip executed")


def rejects(fn):
    try:
        fn()
    except (TypeError, ValueError):
        return
    raise AssertionError("expected fail-closed rejection")


healthy = evaluate(None, {
    "connector_id": "github.main",
    "auth_method": "oauth",
    "health": {"auth_status": "valid", "provider_version_status": "supported"},
})
assert healthy == {
    "connector_id": "github.main", "events": (), "important": False,
    "settings_deep_link": "settings://connectors/github.main",
}

migrated = evaluate(
    {"connector_id": "example", "auth_method": "api_key"},
    {"connector_id": "example", "auth_method": "oauth",
     "health": {"auth_status": "expired", "provider_version_status": "deprecated"}},
)
assert migrated["events"] == ("auth_expired", "provider_deprecated", "auth_method_migration")
assert migrated["important"] is True

# IDs are safe for deep links and bounded; no path/query injection.
for bad in ("../github", "github/other", "github?x=1", " github ", "x" * 129):
    rejects(lambda bad=bad: evaluate(None, {"connector_id": bad, "auth_method": "oauth"}))

# Provider-controlled scalar subclasses must never execute equality/hash/strip hooks.
rejects(lambda: evaluate(None, {"connector_id": HostileStr("github"), "auth_method": "oauth"}))
subclass_auth = evaluate(None, {"connector_id": "github", "auth_method": HostileStr("oauth")})
assert subclass_auth["events"] == ("setup_changed",)
subclass_health = evaluate(None, {
    "connector_id": "github", "auth_method": "oauth",
    "health": {"auth_status": HostileStr("expired")},
})
assert subclass_health["events"] == ()

# Container subclasses are not trusted as provider state.
class HostileDict(dict):
    def get(self, *args, **kwargs):
        raise AssertionError("hostile get executed")

rejects(lambda: evaluate(None, HostileDict(connector_id="github")))
# A hostile nested health mapping is ignored rather than executed.
assert evaluate(None, {"connector_id": "github", "auth_method": "oauth", "health": HostileDict()})["events"] == ()

print("connector health monitor regression: PASS")
