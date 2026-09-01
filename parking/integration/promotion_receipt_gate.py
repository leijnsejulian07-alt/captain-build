from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy

SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
ACTIONS = {"approve", "promote", "merge"}
MAX_TTL_SECONDS = 3600
RECEIPT_FIELDS = {
    "schema_version", "receipt_id", "kind", "scope_hash", "session_id",
    "runtime_generation_hash", "profile_id", "worktree_fingerprint_hash",
    "authorized_action", "issued_at", "expires_at", "consumed",
    "consumed_action", "consumed_at",
}


def _need_id(name, value):
    value = str(value or "")
    if not SAFE_ID.fullmatch(value):
        raise ValueError(f"valid {name} required")
    return value


def _need_action(value):
    value = str(value or "")
    if value not in ACTIONS:
        raise ValueError("unsupported promotion action")
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


def _canonical_receipt_bytes(row):
    if not isinstance(row, dict) or set(row) != RECEIPT_FIELDS:
        raise ValueError("invalid validation receipt schema")
    return json.dumps(
        row, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def receipt_state_token(row):
    """Opaque CAS token for the exact stored receipt row; contains no secrets."""
    return hashlib.sha256(_canonical_receipt_bytes(row)).hexdigest()


def issue_receipt(*, receipt_id, chat_id, project_id, repo_scope, session_id,
                  runtime_generation, profile_id, worktree_fingerprint,
                  issued_at, expires_at, validation_status, authorized_action):
    receipt_id = _need_id("receipt_id", receipt_id)
    session_id = _need_id("session_id", session_id)
    profile_id = _need_id("profile_id", profile_id)
    authorized_action = _need_action(authorized_action)
    if validation_status != "pass":
        raise ValueError("only passing validation may issue a receipt")
    if not isinstance(issued_at, int) or isinstance(issued_at, bool):
        raise ValueError("issued_at must be int")
    if not isinstance(expires_at, int) or isinstance(expires_at, bool):
        raise ValueError("expires_at must be int")
    if expires_at <= issued_at or expires_at - issued_at > MAX_TTL_SECONDS:
        raise ValueError("receipt ttl invalid")
    return {
        "schema_version": 2,
        "receipt_id": receipt_id,
        "kind": "validation-pass",
        "scope_hash": _scope_hash(chat_id, project_id, repo_scope),
        "session_id": session_id,
        "runtime_generation_hash": _fingerprint(runtime_generation),
        "profile_id": profile_id,
        "worktree_fingerprint_hash": _fingerprint(worktree_fingerprint),
        "authorized_action": authorized_action,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "consumed": False,
        "consumed_action": None,
        "consumed_at": None,
    }


def _validated_consumption_row(ledger, *, receipt_id, action, chat_id, project_id,
                               repo_scope, session_id, runtime_generation, profile_id,
                               current_worktree_fingerprint, now):
    if not isinstance(ledger, dict):
        raise ValueError("receipt ledger required")
    receipt_id = _need_id("receipt_id", receipt_id)
    action = _need_action(action)
    if not isinstance(now, int) or isinstance(now, bool):
        raise ValueError("now must be int")
    stored = ledger.get(receipt_id)
    if not isinstance(stored, dict):
        raise ValueError("unknown validation receipt")
    row = deepcopy(stored)
    _canonical_receipt_bytes(row)
    if row.get("schema_version") != 2 or row.get("kind") != "validation-pass":
        raise ValueError("invalid validation receipt")
    if row.get("receipt_id") != receipt_id:
        raise ValueError("receipt id mismatch")
    if row.get("consumed") is not False or row.get("consumed_action") is not None or row.get("consumed_at") is not None:
        raise ValueError("validation receipt already consumed or malformed")
    if row.get("authorized_action") != action:
        raise ValueError("validation receipt action mismatch")
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
    return receipt_id, action, row


def prepare_receipt_consumption(ledger, **kwargs):
    """Prepare an atomic compare-and-swap mutation; this does not consume by itself."""
    receipt_id, action, row = _validated_consumption_row(ledger, **kwargs)
    expected_state_token = receipt_state_token(row)
    row["consumed"] = True
    row["consumed_action"] = action
    row["consumed_at"] = kwargs["now"]
    return {
        "receipt_id": receipt_id,
        "expected_state_token": expected_state_token,
        "replacement": row,
        "replacement_state_token": receipt_state_token(row),
        "accepted": True,
        "action": action,
    }


def apply_prepared_consumption(ledger, plan):
    """In-memory CAS reference. Durable stores must perform the same CAS atomically."""
    if not isinstance(ledger, dict) or not isinstance(plan, dict):
        raise ValueError("ledger and consumption plan required")
    receipt_id = _need_id("receipt_id", plan.get("receipt_id"))
    expected = str(plan.get("expected_state_token") or "")
    replacement = plan.get("replacement")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("valid expected receipt state token required")
    current = ledger.get(receipt_id)
    if not isinstance(current, dict) or receipt_state_token(current) != expected:
        raise ValueError("receipt state changed before atomic consume")
    if not isinstance(replacement, dict) or receipt_state_token(replacement) != plan.get("replacement_state_token"):
        raise ValueError("invalid replacement receipt state")
    updated = dict(ledger)
    updated[receipt_id] = deepcopy(replacement)
    return updated, {"receipt_id": receipt_id, "accepted": True, "action": replacement["consumed_action"]}


def consume_receipt(ledger, **kwargs):
    """Compatibility helper for single-process tests; production integration must use atomic CAS."""
    return apply_prepared_consumption(ledger, prepare_receipt_consumption(ledger, **kwargs))
