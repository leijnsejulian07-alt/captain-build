"""Regression for connector notice persistence/remediation semantics."""
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

# Resolution automatically clears the notice.
healthy=c(ready=True, health={"status":"healthy","auth_status":"valid","provider_version_status":"current"})
assert notice_for(healthy, NOW) is None

# Provider migrations are important even with valid credentials.
m=notice_for(c(health={"status":"blocked","auth_status":"valid","provider_version_status":"migration_required"}), NOW)
assert m["code"] == "migration_required" and m["important"]

# Never persist arbitrary provider/health messages that could contain sensitive details.
secretish=c(health={"status":"blocked","auth_status":"invalid","provider_version_status":"current","safe_message":"token=DO_NOT_PERSIST"})
s=notice_for(secretish, NOW)
assert "DO_NOT_PERSIST" not in repr(s) and "safe_message" not in s

# Missing remediation deep-link falls back to a connector-scoped Settings route.
f=notice_for(c(remediation=None), NOW)
assert f["settings_section"] == "settings/connectors/github"
print("CONNECTOR_NOTICE_POLICY_OK")
