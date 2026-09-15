from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Mapping

SCHEMA_VERSION = 1
MAX_RECEIPT_AGE_SECONDS = 7 * 24 * 60 * 60
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_HEAD_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


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


def _scope_digest(
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    state_epoch: int,
    builder_session_id: str,
) -> str:
    if not all(isinstance(value, str) and value for value in (chat_id, project_id, repo_scope, builder_session_id)):
        raise ValueError("invalid mutation receipt scope")
    if isinstance(state_epoch, bool) or not isinstance(state_epoch, int) or state_epoch < 0:
        raise ValueError("invalid state_epoch")
    return _binding(
        {
            "chat_id": chat_id,
            "project_id": project_id,
            "repo_scope": repo_scope,
            "state_epoch": state_epoch,
            "builder_session_id": builder_session_id,
        }
    )


def issue_builder_mutation_receipt(
    *,
    mutation_id: str,
    source_request_id: str,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    state_epoch: int,
    builder_session_id: str,
    revision: int,
    artifact_digest: str,
    review_binding_digest: str,
    handle_scope_digest: str,
    pre_git_head: str,
    pre_worktree_digest: str,
    pre_state_digest: str,
    post_git_head: str,
    post_worktree_digest: str,
    post_state_digest: str,
    rollback_checkpoint_binding: str,
    created_at: str,
) -> dict[str, object]:
    mutation = _id(mutation_id, "mutation_id")
    request = _id(source_request_id, "source_request_id")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("invalid revision")
    artifact = _digest(artifact_digest, "artifact_digest")
    review = _digest(review_binding_digest, "review_binding_digest")
    handle_scope = _digest(handle_scope_digest, "handle_scope_digest")
    pre_head = _git_head(pre_git_head, "pre_git_head")
    pre_worktree = _digest(pre_worktree_digest, "pre_worktree_digest")
    pre_state = _digest(pre_state_digest, "pre_state_digest")
    post_head = _git_head(post_git_head, "post_git_head")
    post_worktree = _digest(post_worktree_digest, "post_worktree_digest")
    post_state = _digest(post_state_digest, "post_state_digest")
    rollback = _digest(rollback_checkpoint_binding, "rollback_checkpoint_binding")
    _timestamp(created_at, "created_at")

    if (pre_head, pre_worktree, pre_state) == (post_head, post_worktree, post_state):
        raise ValueError("mutation receipt has no state transition")

    row: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "mutation_id": mutation,
        "source_request_id": request,
        "scope_digest": _scope_digest(
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            state_epoch=state_epoch,
            builder_session_id=builder_session_id,
        ),
        "revision": revision,
        "artifact_digest": artifact,
        "review_binding_digest": review,
        "handle_scope_digest": handle_scope,
        "pre_git_head": pre_head,
        "pre_worktree_digest": pre_worktree,
        "pre_state_digest": pre_state,
        "post_git_head": post_head,
        "post_worktree_digest": post_worktree,
        "post_state_digest": post_state,
        "rollback_checkpoint_binding": rollback,
        "created_at": created_at,
    }
    row["binding_digest"] = _binding(row)
    return row


def validate_builder_mutation_receipt(
    receipt: Mapping[str, object],
    *,
    mutation_id: str,
    source_request_id: str,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    state_epoch: int,
    builder_session_id: str,
    revision: int,
    artifact_digest: str,
    review_binding_digest: str,
    handle_scope_digest: str,
    current_git_head: str,
    current_worktree_digest: str,
    current_state_digest: str,
    rollback_checkpoint_binding: str,
    now: str,
) -> dict[str, object]:
    required = {
        "schema_version",
        "mutation_id",
        "source_request_id",
        "scope_digest",
        "revision",
        "artifact_digest",
        "review_binding_digest",
        "handle_scope_digest",
        "pre_git_head",
        "pre_worktree_digest",
        "pre_state_digest",
        "post_git_head",
        "post_worktree_digest",
        "post_state_digest",
        "rollback_checkpoint_binding",
        "created_at",
        "binding_digest",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != required:
        raise ValueError("invalid builder mutation receipt schema")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported builder mutation receipt schema")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("invalid revision")

    expected = {
        "mutation_id": _id(mutation_id, "mutation_id"),
        "source_request_id": _id(source_request_id, "source_request_id"),
        "scope_digest": _scope_digest(
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            state_epoch=state_epoch,
            builder_session_id=builder_session_id,
        ),
        "revision": revision,
        "artifact_digest": _digest(artifact_digest, "artifact_digest"),
        "review_binding_digest": _digest(review_binding_digest, "review_binding_digest"),
        "handle_scope_digest": _digest(handle_scope_digest, "handle_scope_digest"),
        "post_git_head": _git_head(current_git_head, "current_git_head"),
        "post_worktree_digest": _digest(current_worktree_digest, "current_worktree_digest"),
        "post_state_digest": _digest(current_state_digest, "current_state_digest"),
        "rollback_checkpoint_binding": _digest(rollback_checkpoint_binding, "rollback_checkpoint_binding"),
    }
    for field, wanted in expected.items():
        actual = receipt.get(field)
        if isinstance(wanted, str):
            if not isinstance(actual, str) or not hmac.compare_digest(actual, wanted):
                raise PermissionError(f"builder mutation receipt {field} mismatch")
        elif actual != wanted:
            raise PermissionError(f"builder mutation receipt {field} mismatch")

    _git_head(receipt.get("pre_git_head"), "pre_git_head")
    _digest(receipt.get("pre_worktree_digest"), "pre_worktree_digest")
    _digest(receipt.get("pre_state_digest"), "pre_state_digest")

    created = _timestamp(receipt.get("created_at"), "created_at")
    current_time = _timestamp(now, "now")
    if created > current_time:
        raise PermissionError("builder mutation receipt is from the future")
    if (current_time - created).total_seconds() > MAX_RECEIPT_AGE_SECONDS:
        raise PermissionError("builder mutation receipt is stale")

    digest = _digest(receipt.get("binding_digest"), "binding_digest")
    unsigned = dict(receipt)
    unsigned.pop("binding_digest")
    if not hmac.compare_digest(digest, _binding(unsigned)):
        raise ValueError("builder mutation receipt was modified")
    return dict(receipt)
