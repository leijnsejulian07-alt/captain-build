"""Regression for connector notice persistence/remediation and scope semantics."""
from datetime import datetime, timedelta, timezone
from connector_notice_policy import notice_for, visible
from connector_readiness import evaluate

NOW = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)


def c(**kw):
    x = {
        "connector_id": "github", "installed": True, "connected": True,
        "enabled": True, "ready": False, "auth_method": "oauth",
        "health": {"status": "blocked", "auth_status": "reauth_required",
                   "provider_version_status": "current"},
        "remediation": {"settings_section": "settings/connectors/github",
                        "remind_after": None},
    }
    x.update(kw)
    return x


n = notice_for(c(), NOW)
assert n["code"] == "reauth_required" and n["important"]
assert n["settings_section"] == "settings/connectors/github"
assert set(n) == {"connector_id", "code", "important", "settings_section",
                  "remind_after", "generated_at"}
assert visible(n, None, NOW)
assert not visible(n, NOW, NOW + timedelta(hours=23))
assert visible(n, NOW, NOW + timedelta(hours=24))
assert not visible(n, None, NOW, chat_id="c1", project_id="p1",
                   repo_scope_hash="h1", state_epoch=7)

# Project notices are bound to the complete Captain authority tuple.
scope = {"chat_id": "c1", "project_id": "p1", "repo_scope_hash": "h1",
         "state_epoch": 7}
p = notice_for(c(**scope), NOW)
assert all(p[k] == v for k, v in scope.items())
assert visible(p, None, NOW, **scope)
for wrong in (
    {**scope, "chat_id": "c2"}, {**scope, "project_id": "p2"},
    {**scope, "repo_scope_hash": "h2"}, {**scope, "state_epoch": 8},
):
    assert not visible(p, None, NOW, **wrong)
assert not visible(p, None, NOW)

# Partial/malformed/raw project scope fails closed at creation.
for bad in (
    {"project_id": "p1", "state_epoch": 7},
    {"chat_id": "c1", "project_id": "p1", "repo_scope_hash": "h1"},
    {**scope, "state_epoch": True}, {**scope, "state_epoch": 0},
    {**scope, "repo_scope_hash": ""}, {**scope, "repo_scope": "C:/secret/repo"},
):
    try:
        notice_for(c(**bad), NOW)
    except ValueError:
        pass
    else:
        raise AssertionError(f"malformed scope accepted: {bad!r}")

# Malformed persisted scope also fails closed at read time.
corrupt = dict(p)
corrupt.pop("repo_scope_hash")
assert not visible(corrupt, None, NOW, **scope)

# Readiness is derived; a persisted/provider ready bit cannot override bad auth.
healthy = c(ready=False, health={"status": "healthy", "auth_status": "valid",
                                "provider_version_status": "current"})
assert evaluate(healthy)["ready"] is True
assert notice_for(healthy, NOW) is None
expired = c(ready=True, health={"status": "blocked", "auth_status": "expired",
                               "provider_version_status": "current"})
assert evaluate(expired)["ready"] is False
assert notice_for(expired, NOW)["code"] == "auth_expired"
unknown_auth = c(auth_method="future_magic", ready=True,
                 health={"status": "healthy", "auth_status": "valid",
                         "provider_version_status": "current"})
assert evaluate(unknown_auth)["ready"] is False

m = notice_for(c(health={"status": "blocked", "auth_status": "valid",
                         "provider_version_status": "migration_required"}), NOW)
assert m["code"] == "migration_required" and m["important"]
secretish = c(health={"status": "blocked", "auth_status": "invalid",
                      "provider_version_status": "current",
                      "safe_message": "token=DO_NOT_PERSIST"})
s = notice_for(secretish, NOW)
assert "DO_NOT_PERSIST" not in repr(s) and "safe_message" not in s

# Remediation may only deep-link inside the owning connector subtree.
for section in ("https://evil.invalid", "settings/connectors/../github",
                "settings/connectors/slack/permissions"):
    try:
        notice_for(c(remediation={"settings_section": section}), NOW)
    except ValueError:
        pass
    else:
        raise AssertionError(f"unsafe remediation accepted: {section!r}")
assert notice_for(c(remediation={"settings_section":
                                 "settings/connectors/github/permissions"}), NOW)["settings_section"].endswith("/permissions")
assert notice_for(c(remediation=None), NOW)["settings_section"] == "settings/connectors/github"
print("CONNECTOR_NOTICE_POLICY_OK")
