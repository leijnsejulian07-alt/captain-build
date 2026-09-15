from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from parking.integration.builder_session_contract import authorize_builder_action
from parking.integration.scope_contract import parse_scope


class BuilderSessionStoreError(ValueError):
    pass


@dataclass(frozen=True)
class BuilderSessionRef:
    session_id: str
    state_epoch: int
    binding_digest: str


def _scope_digest(*, chat_id: str, project_id: str, repo_scope: str) -> str:
    scope = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    raw = json.dumps(scope.as_dict(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class BuilderSessionAuthorityStore:
    """Metadata-only authority index for active Captain builder sessions.

    Session envelopes remain the source of truth. This index stores only session id,
    scope digest, Project State epoch and the existing binding digest so a verified epoch
    transition can eagerly revoke stale session authority without retaining prompts,
    code, repo paths, file contents, credentials or provider payloads.
    """

    def __init__(self) -> None:
        self._records: dict[str, tuple[str, int, str]] = {}

    def register(
        self,
        session: Mapping[str, object],
        *,
        chat_id: str,
        project_id: str,
        repo_scope: str,
    ) -> BuilderSessionRef:
        if not isinstance(session, Mapping):
            raise BuilderSessionStoreError("invalid builder session")
        session_id = session.get("session_id")
        state_epoch = session.get("state_epoch")
        binding_digest = session.get("binding_digest")
        if not isinstance(session_id, str) or not session_id:
            raise BuilderSessionStoreError("invalid builder session_id")
        if isinstance(state_epoch, bool) or not isinstance(state_epoch, int) or state_epoch < 1:
            raise BuilderSessionStoreError("invalid builder state_epoch")
        if not isinstance(binding_digest, str) or len(binding_digest) != 64:
            raise BuilderSessionStoreError("invalid builder binding_digest")
        digest = _scope_digest(chat_id=chat_id, project_id=project_id, repo_scope=repo_scope)
        record = (digest, state_epoch, binding_digest)
        existing = self._records.get(session_id)
        if existing is not None and existing != record:
            raise BuilderSessionStoreError("session_id already bound to different authority")
        self._records[session_id] = record
        return BuilderSessionRef(session_id=session_id, state_epoch=state_epoch, binding_digest=binding_digest)

    def authorize(
        self,
        session: Mapping[str, object],
        *,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        session_id: str,
        repo_head: str,
        worktree_digest: str,
        state_epoch: int,
        capability: str,
        now: str,
    ) -> BuilderSessionRef:
        digest = _scope_digest(chat_id=chat_id, project_id=project_id, repo_scope=repo_scope)
        record = self._records.get(session_id)
        if record is None:
            raise PermissionError("builder session authority unavailable")
        binding_digest = session.get("binding_digest") if isinstance(session, Mapping) else None
        if record != (digest, state_epoch, binding_digest):
            raise PermissionError("builder session authority changed")
        authorize_builder_action(
            session,
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            session_id=session_id,
            repo_head=repo_head,
            worktree_digest=worktree_digest,
            state_epoch=state_epoch,
            capability=capability,
            now=now,
        )
        return BuilderSessionRef(session_id=session_id, state_epoch=state_epoch, binding_digest=str(binding_digest))

    def revoke_stale_epochs(
        self,
        *,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        current_epoch: int,
    ) -> int:
        if isinstance(current_epoch, bool) or not isinstance(current_epoch, int) or current_epoch < 1:
            raise BuilderSessionStoreError("invalid current_epoch")
        digest = _scope_digest(chat_id=chat_id, project_id=project_id, repo_scope=repo_scope)
        stale = [session_id for session_id, (scope, epoch, _) in self._records.items()
                 if scope == digest and epoch != current_epoch]
        for session_id in stale:
            del self._records[session_id]
        return len(stale)

    def count(self) -> int:
        return len(self._records)
