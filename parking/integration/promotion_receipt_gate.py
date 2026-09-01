from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy

SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
ACTIONS = {"approve", "promote", "merge"}
MAX_TTL_SECONDS = 3600


def _need_id(name, value):
    value = str(value or "")
    if not SAFE_ID.fullmatch(value):
        raise ValueError(f"valid {name} required")
    return value


def _scope_hash(chat_id, project_id, repo_scope):
    chat_id = _need_id("chat_id", chat_id)
    project_id = _need_id("project_id", project_id)
    repo_scope = str(repo_scope or "")
    if not repo_scope or len(repo_scope) > 2048:
        raise ValueError("repo_scope required")
    raw = json.dumps([chat_id, project_id, repo_scope], separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fingerprint(value):
    value = str(value or "")
    if not value or len(value) > 512:
        raise ValueError("fingerprint value required")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_receipt(*, receipt_id, chat_id, project_id, repo_scope, session_id,
                  runtime_generation, profile_id, worktree_fingerprint,
                  issued_at, expires_at, validation_status):
    receipt_id = _need_id("receipt_id", receipt_id)
    session_id = _need_id("session_id", session_id)
    profile_id = _need_id("profile_id", profile_id)
    if validation_status != "pass":
        raise ValueError("only passing validation may issue a receipt")
    if not isinstance(issued_at, int) or isinstance(issued_at, bool):
        raise ValueError("issued_at must be int")
    if not isinstance(expires_at, int) or isinstance(expires_at, bool):
        raise ValueError("expires_at must be int")
    if expires_at <= issued_at or expires_at - issued_at > MAX_TTL_SECONDS:
        raise ValueError("receipt ttl invalid")
    return {
        "schema_version": 1,
        "receipt_id": receipt_id,
        "kind": "validation-pass",
        "scope_hash": _scope_hash(chat_id, project_id, repo_scope),
        "session_id": session_id,
        "runtime_generation_hash": _fingerprint(runtime_generation),
        "profile_id": profile_id,
        "worktree_fingerprint_hash": _fingerprint(worktree_fingerprint),
        "issued_at": issued_at,
        "expires_at": expires_at,
        "consumed": False,
        "consumed_action": None,
        "consumed_at": None,
    }


def consume_receipt(ledger, *, receipt_id, action, chat_id, project_id, repo_scope,
                    session_id, runtime_generation, profile_id,
                    current_worktree_fingerprint, now):
    if not isinstance(ledger, dict):
        raise ValueError("receipt ledger required")
    receipt_id = _need_id("receipt_id", receipt_id)
    action = str(action or "")
    if action not in ACTIONS:
        raise ValueError("unsupported promotion action")
    if not isinstance(now, int) or isinstance(now, bool):
        raise ValueError("now must be int")
    stored = ledger.get(receipt_id)
    if not isinstance(stored, dict):
        raise ValueError("unknown validation receipt")
    row = deepcopy(stored)
    if row.get("schema_version") != 1 or row.get("kind") != "validation-pass":
        raise ValueError("invalid validation receipt")
    if row.get("receipt_id") != receipt_id:
        raise ValueError("receipt id mismatch")
    if row.get("consumed") is not False:
        raise ValueError("validation receipt already consumed")
    if row.get("scope_hash") != _scope_hash(chat_id, project_id, repo_scope):
        raise ValueError("validation receipt scope mismatch")
    if row.get("session_id") != _need_id("session_id", session_id):
        raise ValueError("validation receipt session mismatch")
    if row.get("runtime_generation_hash") != _fingerprint(runtime_generation):
        raise ValueError("validation receipt runtime mismatch")
    if row.get("profile_id") != _need_id("profile_id", profile_id):
        raise ValueError("validation receipt profile mismatch")
    if row.get("worktree_fingerprint_hash") != _fingerprint(current_worktree_fingerprint):
        raise ValueError("validation receipt worktree mismatch")
    issued_at, expires_at = row.get("issued_at"), row.get("expires_at")
    if not isinstance(issued_at, int) or isinstance(issued_at, bool):
        raise ValueError("invalid receipt issued_at")
    if not isinstance(expires_at, int) or isinstance(expires_at, bool):
        raise ValueError("invalid receipt expires_at")
    if expires_at <= issued_at or expires_at - issued_at > MAX_TTL_SECONDS:
        raise ValueError("invalid receipt ttl")
    if now < issued_at or now > expires_at:
        raise ValueError("validation receipt expired or not yet valid")
    row["consumed"] = True
    row["consumed_action"] = action
    row["consumed_at"] = now
    updated = dict(ledger)
    updated[receipt_id] = row
    return updated, {"receipt_id": receipt_id, "accepted": True, "action": action}
