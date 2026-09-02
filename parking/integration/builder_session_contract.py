from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Mapping, Sequence

from parking.integration.scope_contract import ScopeKey, parse_scope

SCHEMA_VERSION = 1
MAX_TTL_SECONDS = 8 * 60 * 60
MAX_CAPABILITIES = 16
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_CAP_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
ALLOWED_CAPABILITIES = frozenset({
    "console_read", "diff_read", "diff_write", "file_read", "file_write",
    "preview_open", "preview_reload", "rollback", "test_run",
})


def _dt(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"invalid {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"invalid {field}")
    return parsed.astimezone(timezone.utc)


def _caps(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("capabilities must be a sequence")
    caps = tuple(value)
    if not caps or len(caps) > MAX_CAPABILITIES:
        raise ValueError("invalid capability count")
    if any(not isinstance(item, str) or not _CAP_RE.fullmatch(item) for item in caps):
        raise ValueError("invalid capability")
    if any(item not in ALLOWED_CAPABILITIES for item in caps):
        raise ValueError("unknown capability")
    if tuple(sorted(caps)) != caps or len(set(caps)) != len(caps):
        raise ValueError("capabilities must be canonical and unique")
    return caps


def _binding(scope: ScopeKey, *, session_id: str, repo_head: str, worktree_digest: str,
             state_epoch: int, capabilities: tuple[str, ...], created_at: str, expires_at: str) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "scope": scope.as_dict(),
        "session_id": session_id,
        "repo_head": repo_head,
        "worktree_digest": worktree_digest,
        "state_epoch": state_epoch,
        "capabilities": list(capabilities),
        "created_at": created_at,
        "expires_at": expires_at,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def issue_builder_session(*, chat_id: str, project_id: str, repo_scope: str, session_id: str,
                          repo_head: str, worktree_digest: str, state_epoch: int,
                          capabilities: Sequence[str], created_at: str, expires_at: str) -> dict[str, object]:
    scope = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    if not isinstance(session_id, str) or not _SESSION_RE.fullmatch(session_id):
        raise ValueError("invalid session_id")
    if not isinstance(repo_head, str) or not _SHA_RE.fullmatch(repo_head):
        raise ValueError("invalid repo_head")
    if not isinstance(worktree_digest, str) or not _DIGEST_RE.fullmatch(worktree_digest):
        raise ValueError("invalid worktree_digest")
    if isinstance(state_epoch, bool) or not isinstance(state_epoch, int) or state_epoch < 1:
        raise ValueError("invalid state_epoch")
    caps = _caps(capabilities)
    created = _dt(created_at, "created_at")
    expires = _dt(expires_at, "expires_at")
    ttl = (expires - created).total_seconds()
    if ttl <= 0 or ttl > MAX_TTL_SECONDS:
        raise ValueError("builder session ttl out of bounds")
    row = {
        "schema_version": SCHEMA_VERSION, "scope": scope.as_dict(), "session_id": session_id,
        "repo_head": repo_head, "worktree_digest": worktree_digest, "state_epoch": state_epoch,
        "capabilities": list(caps), "created_at": created_at, "expires_at": expires_at,
    }
    row["binding_digest"] = _binding(scope, session_id=session_id, repo_head=repo_head,
        worktree_digest=worktree_digest, state_epoch=state_epoch, capabilities=caps,
        created_at=created_at, expires_at=expires_at)
    return row


def authorize_builder_action(session: Mapping[str, object], *, chat_id: str, project_id: str,
                             repo_scope: str, session_id: str, repo_head: str,
                             worktree_digest: str, state_epoch: int, capability: str,
                             now: str) -> dict[str, object]:
    required = {"schema_version", "scope", "session_id", "repo_head", "worktree_digest",
                "state_epoch", "capabilities", "created_at", "expires_at", "binding_digest"}
    if not isinstance(session, Mapping) or set(session) != required or session.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid builder session schema")
    scope = parse_scope(session.get("scope"))
    expected = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    if scope != expected:
        raise PermissionError("builder session scope mismatch")
    if session.get("session_id") != session_id:
        raise PermissionError("builder session mismatch")
    if session.get("repo_head") != repo_head or session.get("worktree_digest") != worktree_digest:
        raise PermissionError("builder workspace changed")
    if session.get("state_epoch") != state_epoch:
        raise PermissionError("builder state epoch changed")
    caps = _caps(session.get("capabilities"))
    if capability not in caps:
        raise PermissionError("builder capability denied")
    created_at, expires_at = session.get("created_at"), session.get("expires_at")
    created, expires, current = _dt(created_at, "created_at"), _dt(expires_at, "expires_at"), _dt(now, "now")
    if current < created or current > expires:
        raise PermissionError("builder session expired or not active")
    digest = session.get("binding_digest")
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise ValueError("invalid builder session binding")
    expected_digest = _binding(scope, session_id=session_id, repo_head=repo_head,
        worktree_digest=worktree_digest, state_epoch=state_epoch, capabilities=caps,
        created_at=created_at, expires_at=expires_at)
    if digest != expected_digest:
        raise ValueError("builder session was modified")
    return dict(session)
