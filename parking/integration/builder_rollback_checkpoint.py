from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Mapping

from parking.integration.scope_contract import parse_scope

SCHEMA_VERSION = 1
MAX_CHECKPOINT_AGE_SECONDS = 7 * 24 * 60 * 60
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_HEAD_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ALLOWED_SOURCE_ACTIONS = frozenset({"files", "rollback"})


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def _git_head(value: object, field: str) -> str:
    if not isinstance(value, str) or not _GIT_HEAD_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def _id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")
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


def issue_builder_rollback_checkpoint(
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    checkpoint_id: str,
    source_request_id: str,
    source_action: str,
    source_action_binding: str,
    session_binding: str,
    context_binding: str,
    target_git_head: str,
    target_worktree_digest: str,
    target_state_digest: str,
    target_snapshot_digest: str,
    expected_current_git_head: str,
    expected_current_worktree_digest: str,
    expected_current_state_digest: str,
    created_at: str,
) -> dict[str, object]:
    scope = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    checkpoint = _id(checkpoint_id, "checkpoint_id")
    request = _id(source_request_id, "source_request_id")
    if source_action not in _ALLOWED_SOURCE_ACTIONS:
        raise ValueError("unsupported rollback source action")
    source_binding = _digest(source_action_binding, "source_action_binding")
    session = _digest(session_binding, "session_binding")
    context = _digest(context_binding, "context_binding")
    target_head = _git_head(target_git_head, "target_git_head")
    target_worktree = _digest(target_worktree_digest, "target_worktree_digest")
    target_state = _digest(target_state_digest, "target_state_digest")
    target_snapshot = _digest(target_snapshot_digest, "target_snapshot_digest")
    current_head = _git_head(expected_current_git_head, "expected_current_git_head")
    current_worktree = _digest(expected_current_worktree_digest, "expected_current_worktree_digest")
    current_state = _digest(expected_current_state_digest, "expected_current_state_digest")
    _timestamp(created_at, "created_at")

    if target_state == current_state and target_worktree == current_worktree and target_head == current_head:
        raise ValueError("rollback checkpoint has no state transition")

    row: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "scope": scope.as_dict(),
        "checkpoint_id": checkpoint,
        "source_request_id": request,
        "source_action": source_action,
        "source_action_binding": source_binding,
        "session_binding": session,
        "context_binding": context,
        "target_git_head": target_head,
        "target_worktree_digest": target_worktree,
        "target_state_digest": target_state,
        "target_snapshot_digest": target_snapshot,
        "expected_current_git_head": current_head,
        "expected_current_worktree_digest": current_worktree,
        "expected_current_state_digest": current_state,
        "created_at": created_at,
    }
    row["binding_digest"] = _binding(row)
    return row


def validate_builder_rollback_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    checkpoint_id: str,
    source_request_id: str,
    source_action_binding: str,
    session_binding: str,
    context_binding: str,
    current_git_head: str,
    current_worktree_digest: str,
    current_state_digest: str,
    now: str,
) -> dict[str, object]:
    required = {
        "schema_version",
        "scope",
        "checkpoint_id",
        "source_request_id",
        "source_action",
        "source_action_binding",
        "session_binding",
        "context_binding",
        "target_git_head",
        "target_worktree_digest",
        "target_state_digest",
        "target_snapshot_digest",
        "expected_current_git_head",
        "expected_current_worktree_digest",
        "expected_current_state_digest",
        "created_at",
        "binding_digest",
    }
    if not isinstance(checkpoint, Mapping) or set(checkpoint) != required:
        raise ValueError("invalid builder rollback checkpoint schema")
    if checkpoint.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported builder rollback checkpoint schema")

    scope = parse_scope(checkpoint.get("scope"))
    expected_scope = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    if scope != expected_scope:
        raise PermissionError("builder rollback checkpoint scope mismatch")

    expected = {
        "checkpoint_id": _id(checkpoint_id, "checkpoint_id"),
        "source_request_id": _id(source_request_id, "source_request_id"),
        "source_action_binding": _digest(source_action_binding, "source_action_binding"),
        "session_binding": _digest(session_binding, "session_binding"),
        "context_binding": _digest(context_binding, "context_binding"),
        "expected_current_git_head": _git_head(current_git_head, "current_git_head"),
        "expected_current_worktree_digest": _digest(current_worktree_digest, "current_worktree_digest"),
        "expected_current_state_digest": _digest(current_state_digest, "current_state_digest"),
    }
    for field, wanted in expected.items():
        actual = checkpoint.get(field)
        if not isinstance(actual, str) or not hmac.compare_digest(actual, wanted):
            raise PermissionError(f"builder rollback checkpoint {field} mismatch")

    if checkpoint.get("source_action") not in _ALLOWED_SOURCE_ACTIONS:
        raise ValueError("invalid rollback source action")
    _git_head(checkpoint.get("target_git_head"), "target_git_head")
    _digest(checkpoint.get("target_worktree_digest"), "target_worktree_digest")
    _digest(checkpoint.get("target_state_digest"), "target_state_digest")
    _digest(checkpoint.get("target_snapshot_digest"), "target_snapshot_digest")

    created = _timestamp(checkpoint.get("created_at"), "created_at")
    current_time = _timestamp(now, "now")
    if created > current_time:
        raise PermissionError("builder rollback checkpoint is from the future")
    if (current_time - created).total_seconds() > MAX_CHECKPOINT_AGE_SECONDS:
        raise PermissionError("builder rollback checkpoint is stale")

    digest = _digest(checkpoint.get("binding_digest"), "binding_digest")
    unsigned = dict(checkpoint)
    unsigned.pop("binding_digest")
    if not hmac.compare_digest(digest, _binding(unsigned)):
        raise ValueError("builder rollback checkpoint was modified")
    return dict(checkpoint)
