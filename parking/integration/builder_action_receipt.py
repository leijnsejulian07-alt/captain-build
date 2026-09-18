from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Mapping

from parking.integration.scope_contract import ScopeKey, parse_scope

SCHEMA_VERSION = 1
MAX_ACTION_AGE_SECONDS = 24 * 60 * 60
_ALLOWED_ACTIONS = frozenset({"files", "diffs", "preview", "console", "tests", "rollback", "context_sync"})
_ALLOWED_RESULTS = frozenset({"succeeded", "failed", "cancelled"})
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def _request_id(value: object) -> str:
    if not isinstance(value, str) or not _REQUEST_RE.fullmatch(value):
        raise ValueError("invalid request_id")
    return value


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"invalid {field}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"invalid {field}")
    return parsed.astimezone(timezone.utc)


def _binding(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def issue_builder_action_receipt(
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    request_id: str,
    action: str,
    session_binding: str,
    context_binding: str,
    before_state_digest: str,
    after_state_digest: str,
    artifact_digest: str,
    result: str,
    started_at: str,
    finished_at: str,
) -> dict[str, object]:
    scope = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    request = _request_id(request_id)
    if action not in _ALLOWED_ACTIONS:
        raise ValueError("unsupported builder action")
    if result not in _ALLOWED_RESULTS:
        raise ValueError("unsupported builder result")
    session = _digest(session_binding, "session_binding")
    context = _digest(context_binding, "context_binding")
    before = _digest(before_state_digest, "before_state_digest")
    after = _digest(after_state_digest, "after_state_digest")
    artifact = _digest(artifact_digest, "artifact_digest")
    started = _timestamp(started_at, "started_at")
    finished = _timestamp(finished_at, "finished_at")
    if finished < started:
        raise ValueError("builder action finished before it started")
    if (finished - started).total_seconds() > MAX_ACTION_AGE_SECONDS:
        raise ValueError("builder action duration exceeds bound")

    row: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "scope": scope.as_dict(),
        "request_id": request,
        "action": action,
        "session_binding": session,
        "context_binding": context,
        "before_state_digest": before,
        "after_state_digest": after,
        "artifact_digest": artifact,
        "result": result,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    row["binding_digest"] = _binding(row)
    return row


def validate_builder_action_receipt(
    receipt: Mapping[str, object],
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    request_id: str,
    action: str,
    session_binding: str,
    context_binding: str,
    before_state_digest: str,
    after_state_digest: str,
    artifact_digest: str,
    now: str,
) -> dict[str, object]:
    required = {
        "schema_version",
        "scope",
        "request_id",
        "action",
        "session_binding",
        "context_binding",
        "before_state_digest",
        "after_state_digest",
        "artifact_digest",
        "result",
        "started_at",
        "finished_at",
        "binding_digest",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != required:
        raise ValueError("invalid builder action receipt schema")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported builder action receipt schema")

    scope = parse_scope(receipt.get("scope"))
    expected_scope = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    if scope != expected_scope:
        raise PermissionError("builder action receipt scope mismatch")

    expected_scalars = {
        "request_id": _request_id(request_id),
        "action": action,
        "session_binding": _digest(session_binding, "session_binding"),
        "context_binding": _digest(context_binding, "context_binding"),
        "before_state_digest": _digest(before_state_digest, "before_state_digest"),
        "after_state_digest": _digest(after_state_digest, "after_state_digest"),
        "artifact_digest": _digest(artifact_digest, "artifact_digest"),
    }
    if action not in _ALLOWED_ACTIONS:
        raise ValueError("unsupported builder action")
    for field, expected in expected_scalars.items():
        actual = receipt.get(field)
        if not isinstance(actual, str) or not hmac.compare_digest(actual, expected):
            raise PermissionError(f"builder action receipt {field} mismatch")

    if receipt.get("result") not in _ALLOWED_RESULTS:
        raise ValueError("invalid builder action result")
    started = _timestamp(receipt.get("started_at"), "started_at")
    finished = _timestamp(receipt.get("finished_at"), "finished_at")
    current = _timestamp(now, "now")
    if finished < started or (finished - started).total_seconds() > MAX_ACTION_AGE_SECONDS:
        raise ValueError("invalid builder action timing")
    if finished > current:
        raise PermissionError("builder action receipt is from the future")
    if (current - finished).total_seconds() > MAX_ACTION_AGE_SECONDS:
        raise PermissionError("builder action receipt is stale")

    digest = _digest(receipt.get("binding_digest"), "binding_digest")
    unsigned = dict(receipt)
    unsigned.pop("binding_digest")
    expected_binding = _binding(unsigned)
    if not hmac.compare_digest(digest, expected_binding):
        raise ValueError("builder action receipt was modified")
    return dict(receipt)
