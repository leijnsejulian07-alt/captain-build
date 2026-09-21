"""Regression for connector notice persistence/remediation and scope semantics."""
from datetime import datetime, timedelta, timezone
from connector_notice_policy import notice_for, visible

NOW = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)

def c(**kw):
    x={"connector_id":"github","installed":True,"connected":True,"enabled":True,"ready":False,
       "health":{"status":"blocked","auth_status":"reauth_required","provider_version_status":"current"},
       "remediation":{"settings_section":"settings/connectors/github","remind_after":None}}
    x.update(kw); return x

n=notice_for(c(), NOW)
assert n["code"] == "reauth_required" and n["important"]
assert n["settings_section"] == "settings/connectors/github"
assert set(n) == {"connector_id","code","important","settings_section","remind_after","generated_at"}
assert visible(n, None, NOW)
assert not visible(n, NOW, NOW + timedelta(hours=23))
assert visible(n, NOW, NOW + timedelta(hours=24))
assert not visible(n, None, NOW, chat_id="c1", project_id="p1", repo_scope="r1", state_epoch=7)

# Project notices are bound to the complete Captain authority tuple.
scope={"chat_id":"c1","project_id":"p1","repo_scope":"r1","state_epoch":7}
p=notice_for(c(**scope), NOW)
assert all(p[k] == v for k,v in scope.items())
assert visible(p, None, NOW, **scope)
for wrong in (
    {**scope,"chat_id":"c2"}, {**scope,"project_id":"p2"},
    {**scope,"repo_scope":"r2"}, {**scope,"state_epoch":8},
):
    assert not visible(p, None, NOW, **wrong)
assert not visible(p, None, NOW)

# Partial/malformed project scope fails closed at creation.
for bad in (
    {"project_id":"p1","state_epoch":7},
    {"chat_id":"c1","project_id":"p1","repo_scope":"r1"},
    {**scope,"state_epoch":True}, {**scope,"repo_scope":""},
):
    try:
        notice_for(c(**bad), NOW)
    except ValueError:
        pass
    else:
        raise AssertionError(f"malformed scope accepted: {bad!r}")

# Malformed persisted scope also fails closed at read time.
corrupt=dict(p); corrupt.pop("repo_scope")
assert not visible(corrupt, None, NOW, **scope)

healthy=c(ready=True, health={"status":"healthy","auth_status":"valid","provider_version_status":"current"})
assert notice_for(healthy, NOW) is None
m=notice_for(c(health={"status":"blocked","auth_status":"valid","provider_version_status":"migration_required"}), NOW)
assert m["code"] == "migration_required" and m["important"]
secretish=c(health={"status":"blocked","auth_status":"invalid","provider_version_status":"current","safe_message":"token=DO_NOT_PERSIST"})
s=notice_for(secretish, NOW)
assert "DO_NOT_PERSIST" not in repr(s) and "safe_message" not in s
f=notice_for(c(remediation=None), NOW)
assert f["settings_section"] == "settings/connectors/github"
print("CONNECTOR_NOTICE_POLICY_OK")
