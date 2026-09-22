from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Mapping

from parking.integration.builder_session_contract import authorize_builder_action
from parking.integration.scope_contract import ScopeKey, parse_scope

SCHEMA_VERSION = 1
MAX_REVISION = 2**63 - 1
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _revision(value: object, field: str, *, allow_zero: bool = False) -> int:
    floor = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < floor or value > MAX_REVISION:
        raise ValueError(f"invalid {field}")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def _binding(
    scope: ScopeKey,
    *,
    session_binding: str,
    captain_memory_revision: int,
    captain_memory_digest: str,
    builder_revision: int,
    builder_state_digest: str,
) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "scope": scope.as_dict(),
        "session_binding": session_binding,
        "captain_memory_revision": captain_memory_revision,
        "captain_memory_digest": captain_memory_digest,
        "builder_revision": builder_revision,
        "builder_state_digest": builder_state_digest,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _authorized_session(
    session: Mapping[str, object],
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    session_id: str,
    repo_head: str,
    worktree_digest: str,
    state_epoch: int,
    now: str,
) -> dict[str, object]:
    return authorize_builder_action(
        session,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        session_id=session_id,
        repo_head=repo_head,
        worktree_digest=worktree_digest,
        state_epoch=state_epoch,
        capability="context_sync",
        now=now,
    )


def issue_builder_context(
    session: Mapping[str, object],
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    session_id: str,
    repo_head: str,
    worktree_digest: str,
    state_epoch: int,
    captain_memory_revision: int,
    captain_memory_digest: str,
    builder_revision: int,
    builder_state_digest: str,
    now: str,
) -> dict[str, object]:
    authorized = _authorized_session(
        session,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        session_id=session_id,
        repo_head=repo_head,
        worktree_digest=worktree_digest,
        state_epoch=state_epoch,
        now=now,
    )
    scope = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    memory_revision = _revision(captain_memory_revision, "captain_memory_revision")
    memory_digest = _digest(captain_memory_digest, "captain_memory_digest")
    local_revision = _revision(builder_revision, "builder_revision", allow_zero=True)
    local_digest = _digest(builder_state_digest, "builder_state_digest")
    session_binding = _digest(authorized.get("binding_digest"), "session_binding")
    row = {
        "schema_version": SCHEMA_VERSION,
        "scope": scope.as_dict(),
        "session_binding": session_binding,
        "captain_memory_revision": memory_revision,
        "captain_memory_digest": memory_digest,
        "builder_revision": local_revision,
        "builder_state_digest": local_digest,
    }
    row["binding_digest"] = _binding(
        scope,
        session_binding=session_binding,
        captain_memory_revision=memory_revision,
        captain_memory_digest=memory_digest,
        builder_revision=local_revision,
        builder_state_digest=local_digest,
    )
    return row


def validate_builder_context(
    context: Mapping[str, object],
    session: Mapping[str, object],
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    session_id: str,
    repo_head: str,
    worktree_digest: str,
    state_epoch: int,
    captain_memory_revision: int,
    captain_memory_digest: str,
    builder_revision: int,
    builder_state_digest: str,
    now: str,
) -> dict[str, object]:
    required = {
        "schema_version", "scope", "session_binding", "captain_memory_revision",
        "captain_memory_digest", "builder_revision", "builder_state_digest", "binding_digest",
    }
    if not isinstance(context, Mapping) or set(context) != required or context.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid builder context schema")
    authorized = _authorized_session(
        session,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        session_id=session_id,
        repo_head=repo_head,
        worktree_digest=worktree_digest,
        state_epoch=state_epoch,
        now=now,
    )
    scope = parse_scope(context.get("scope"))
    expected_scope = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    if scope != expected_scope:
        raise PermissionError("builder context scope mismatch")
    session_binding = _digest(context.get("session_binding"), "session_binding")
    actual_session_binding = _digest(authorized.get("binding_digest"), "session_binding")
    if not hmac.compare_digest(session_binding, actual_session_binding):
        raise PermissionError("builder context session changed")
    recorded_memory_revision = _revision(context.get("captain_memory_revision"), "captain_memory_revision")
    recorded_memory_digest = _digest(context.get("captain_memory_digest"), "captain_memory_digest")
    expected_memory_revision = _revision(captain_memory_revision, "captain_memory_revision")
    expected_memory_digest = _digest(captain_memory_digest, "captain_memory_digest")
    if recorded_memory_revision != expected_memory_revision or not hmac.compare_digest(recorded_memory_digest, expected_memory_digest):
        raise PermissionError("Captain memory advanced; builder context refresh required")
    recorded_builder_revision = _revision(context.get("builder_revision"), "builder_revision", allow_zero=True)
    recorded_builder_digest = _digest(context.get("builder_state_digest"), "builder_state_digest")
    expected_builder_revision = _revision(builder_revision, "builder_revision", allow_zero=True)
    expected_builder_digest = _digest(builder_state_digest, "builder_state_digest")
    if recorded_builder_revision != expected_builder_revision or not hmac.compare_digest(recorded_builder_digest, expected_builder_digest):
        raise PermissionError("builder state changed outside the context bridge")
    digest = _digest(context.get("binding_digest"), "binding_digest")
    expected_binding = _binding(
        scope,
        session_binding=session_binding,
        captain_memory_revision=recorded_memory_revision,
        captain_memory_digest=recorded_memory_digest,
        builder_revision=recorded_builder_revision,
        builder_state_digest=recorded_builder_digest,
    )
    if not hmac.compare_digest(digest, expected_binding):
        raise ValueError("builder context was modified")
    return dict(context)


def advance_builder_context(
    context: Mapping[str, object],
    session: Mapping[str, object],
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    session_id: str,
    repo_head: str,
    worktree_digest: str,
    state_epoch: int,
    captain_memory_revision: int,
    captain_memory_digest: str,
    builder_revision: int,
    builder_state_digest: str,
    next_builder_revision: int,
    next_builder_state_digest: str,
    now: str,
) -> dict[str, object]:
    validate_builder_context(
        context,
        session,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        session_id=session_id,
        repo_head=repo_head,
        worktree_digest=worktree_digest,
        state_epoch=state_epoch,
        captain_memory_revision=captain_memory_revision,
        captain_memory_digest=captain_memory_digest,
        builder_revision=builder_revision,
        builder_state_digest=builder_state_digest,
        now=now,
    )
    next_revision = _revision(next_builder_revision, "next_builder_revision")
    if next_revision != builder_revision + 1:
        raise PermissionError("builder revision must advance exactly once")
    next_digest = _digest(next_builder_state_digest, "next_builder_state_digest")
    return issue_builder_context(
        session,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        session_id=session_id,
        repo_head=repo_head,
        worktree_digest=worktree_digest,
        state_epoch=state_epoch,
        captain_memory_revision=captain_memory_revision,
        captain_memory_digest=captain_memory_digest,
        builder_revision=next_revision,
        builder_state_digest=next_digest,
        now=now,
    )
