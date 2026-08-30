"""Fail-closed capability grants for Captain plugins/subsystems."""
from dataclasses import dataclass
import hashlib, re

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
CAPS = frozenset({"repo:read","repo:write","research:web","builder:run","preview:serve","memory:read","memory:write","connector:use"})

@dataclass(frozen=True)
class Scope:
    chat_id: str
    project_id: str
    repo_scope: str

@dataclass(frozen=True)
class Grant:
    plugin_id: str
    capability: str
    chat_hash: str
    project_hash: str
    repo_hash: str
    enabled: bool = True

def _valid_id(value):
    return isinstance(value, str) and bool(ID_RE.fullmatch(value)) and ".." not in value

def _hash(value):
    if not isinstance(value, str) or not value.strip(): raise ValueError("missing scope")
    return hashlib.sha256(value.encode()).hexdigest()

def issue_grant(plugin_id, capability, scope):
    if not _valid_id(plugin_id): raise ValueError("invalid plugin id")
    if capability not in CAPS: raise ValueError("unknown capability")
    if not isinstance(scope, Scope): raise ValueError("scope required")
    return Grant(plugin_id, capability, _hash(scope.chat_id), _hash(scope.project_id), _hash(scope.repo_scope))

def permits(grant, plugin_id, capability, scope):
    if not isinstance(grant, Grant) or not grant.enabled: return False
    if not _valid_id(plugin_id) or capability not in CAPS or not isinstance(scope, Scope): return False
    return (grant.plugin_id == plugin_id and grant.capability == capability and
            grant.chat_hash == _hash(scope.chat_id) and grant.project_hash == _hash(scope.project_id) and
            grant.repo_hash == _hash(scope.repo_scope))

def public_grant(grant):
    if not isinstance(grant, Grant): raise ValueError("grant required")
    return {"plugin_id": grant.plugin_id, "capability": grant.capability, "enabled": grant.enabled,
            "scope": {"chat": grant.chat_hash, "project": grant.project_hash, "repo": grant.repo_hash}}
