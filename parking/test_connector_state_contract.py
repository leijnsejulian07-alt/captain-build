"""Parking regression for Captain connector state semantics.

Pure stdlib: safe to run before integration. The production Settings registry should
reuse equivalent invariants rather than importing this parking module.
"""
from datetime import datetime, timezone


def validate(s):
    required = {"connector_id","installed","connected","enabled","ready","auth_method","permissions","health"}
    assert isinstance(s, dict) and required <= s.keys()
    assert isinstance(s["connector_id"], str) and s["connector_id"]
    assert s["auth_method"] in {"none","oauth","api_key","id_based","local_session"}
    assert all(isinstance(s[k], bool) for k in ("installed","connected","enabled","ready"))
    assert isinstance(s["permissions"], list) and len(s["permissions"]) == len(set(s["permissions"]))
    h=s["health"]
    assert h["status"] in {"unknown","healthy","degraded","blocked"}
    assert h["auth_status"] in {"not_required","unknown","valid","expired","invalid","reauth_required"}
    assert h["provider_version_status"] in {"unknown","current","deprecated","migration_required"}
    if not s["installed"]:
        assert not s["connected"] and not s["enabled"] and not s["ready"]
    if not s["connected"] or not s["enabled"]:
        assert not s["ready"]
    if s["ready"]:
        assert s["installed"] and s["connected"] and s["enabled"]
        assert h["status"] == "healthy"
        assert h["auth_status"] in {"not_required","valid"}
        assert h["provider_version_status"] in {"unknown","current"}
    # Never infer connection/readiness merely from an auth method being configured.
    if h["auth_status"] in {"expired","invalid","reauth_required"}:
        assert not s["ready"]
    if h["provider_version_status"] in {"deprecated","migration_required"}:
        assert not s["ready"]
    return True


def state(**kw):
    base={"connector_id":"github","installed":True,"connected":True,"enabled":True,"ready":True,
          "auth_method":"oauth","permissions":["repo:read"],
          "health":{"status":"healthy","checked_at":datetime.now(timezone.utc).isoformat(),
                    "auth_status":"valid","provider_version_status":"current"}}
    base.update(kw); return base


def rejects(s):
    try: validate(s)
    except (AssertionError, KeyError, TypeError): return True
    return False

assert validate(state())
assert validate(state(enabled=False, ready=False))
assert validate(state(connected=False, ready=False,
                      health={"status":"blocked","checked_at":None,"auth_status":"reauth_required","provider_version_status":"current"}))
assert rejects(state(ready=True, enabled=False))
assert rejects(state(ready=True, connected=False))
assert rejects(state(ready=True, health={"status":"healthy","checked_at":None,"auth_status":"expired","provider_version_status":"current"}))
assert rejects(state(ready=True, health={"status":"healthy","checked_at":None,"auth_status":"valid","provider_version_status":"migration_required"}))
assert rejects(state(permissions=["repo:read","repo:read"]))
print("CONNECTOR_STATE_CONTRACT_OK")
