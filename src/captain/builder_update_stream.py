"""Epoch-bound realtime OpenBuilder update delivery for Captain.

Builder subsystems may emit console, preview, test, review, debug, diff, rollback
and status events asynchronously. Captain owns the update stream and only
accepts/delivers events for the exact chat/project/repository/Project-State
epoch that authorized the builder session. Delayed events from an old epoch are
therefore rejected instead of appearing in a newly selected project.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Tuple

from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch


UPDATE_KINDS = frozenset(
    {"status", "console", "preview", "test", "review", "debug", "diff", "rollback", "artifact"}
)
BuilderUpdateKey = Tuple[str, str, str, int, str]


def _freeze_payload_value(value: object, *, path: str = "$") -> object:
    """Snapshot update payloads into immutable JSON-like builtin values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AuthorityError(f"builder update payload contains non-finite float at {path}")
        return value
    if type(value) is dict:
        frozen: Dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise AuthorityError(f"builder update payload keys must be non-empty strings at {path}")
            frozen[key] = _freeze_payload_value(nested, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if type(value) in {list, tuple}:
        return tuple(
            _freeze_payload_value(nested, path=f"{path}[{index}]")
            for index, nested in enumerate(value)
        )
    raise AuthorityError(
        "builder update payload contains unsupported mutable/custom value "
        f"at {path}: {type(value).__name__}"
    )


@dataclass(frozen=True)
class BuilderUpdate:
    update_id: str
    session_id: str
    kind: str
    sequence: int
    authority: ProjectAuthority
    payload: Mapping[str, object]

    def validate(self) -> "BuilderUpdate":
        for value, label in ((self.update_id, "update_id"), (self.session_id, "session_id")):
            if not isinstance(value, str) or not value.strip():
                raise AuthorityError(f"builder update requires a non-empty {label}")
        if self.kind not in UPDATE_KINDS:
            raise AuthorityError("unknown builder update kind must fail closed")
        if type(self.sequence) is not int or self.sequence < 0:
            raise AuthorityError("builder update sequence must be a non-negative integer")
        self.authority.validate()
        if self.authority.is_normal_chat:
            raise AuthorityError("builder updates require complete project authority")
        if type(self.payload) is not dict and not isinstance(self.payload, MappingProxyType):
            raise AuthorityError("builder update payload must be a canonical mapping")
        return self


def _snapshot_update(update: BuilderUpdate) -> BuilderUpdate:
    update.validate()
    payload = _freeze_payload_value(dict(update.payload))
    assert isinstance(payload, Mapping)
    return BuilderUpdate(
        update_id=update.update_id,
        session_id=update.session_id,
        kind=update.kind,
        sequence=update.sequence,
        authority=update.authority,
        payload=payload,
    )


class EpochBoundBuilderUpdateStream:
    """Captain-owned, replay-safe realtime builder update stream.

    ``sequence`` is monotonic per (authority, session_id). Duplicate delivery of
    an identical update is idempotent; reusing an update_id with different
    content inside the same authority fails closed. Provider-local update IDs may
    safely repeat across project/repository/epoch walls. Reads re-check the
    active Project State epoch, so stale queued events cannot leak after a
    project transition.
    """

    def __init__(self) -> None:
        self._updates: Dict[BuilderUpdateKey, BuilderUpdate] = {}
        self._last_sequence: Dict[Tuple[ProjectAuthority, str], int] = {}

    @staticmethod
    def _storage_key(authority: ProjectAuthority, update_id: str) -> BuilderUpdateKey:
        authority.validate()
        if authority.is_normal_chat:
            raise AuthorityError("normal chat cannot own builder updates")
        if not isinstance(update_id, str) or not update_id.strip():
            raise AuthorityError("builder update requires a non-empty update_id")
        assert authority.chat_id is not None
        assert authority.project_id is not None
        assert authority.repo_scope is not None
        assert authority.state_epoch is not None
        return (
            authority.chat_id,
            authority.project_id,
            authority.repo_scope,
            authority.state_epoch,
            update_id,
        )

    def publish(
        self,
        update: BuilderUpdate,
        *,
        actor: ProjectAuthority,
        current_epoch: int,
    ) -> bool:
        """Publish one update; return False only for an identical retry."""
        self._validate_actor(actor, current_epoch=current_epoch)
        update.validate()
        actor.require_same_owner(update.authority)

        key = self._storage_key(actor, update.update_id)
        existing = self._updates.get(key)
        if existing is not None:
            candidate = _snapshot_update(update)
            if existing != candidate:
                raise AuthorityError("builder update identity/content is immutable")
            return False

        stream_key = (update.authority, update.session_id)
        last_sequence = self._last_sequence.get(stream_key, -1)
        if update.sequence <= last_sequence:
            raise AuthorityError("builder update sequence must increase monotonically per session")

        self._updates[key] = _snapshot_update(update)
        self._last_sequence[stream_key] = update.sequence
        return True

    def list_readable(
        self,
        *,
        request: ProjectAuthority,
        current_epoch: int,
        session_id: Optional[str] = None,
        after_sequence: Optional[int] = None,
    ) -> List[BuilderUpdate]:
        self._validate_actor(request, current_epoch=current_epoch)
        if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
            raise AuthorityError("session_id filter must be non-empty when provided")
        if after_sequence is not None and (type(after_sequence) is not int or after_sequence < -1):
            raise AuthorityError("after_sequence must be an integer >= -1")

        readable = [
            update
            for update in self._updates.values()
            if update.authority.same_owner(request)
            and (session_id is None or update.session_id == session_id)
            and (after_sequence is None or update.sequence > after_sequence)
        ]
        return sorted(readable, key=lambda update: (update.session_id, update.sequence, update.update_id))

    def revoke_epoch(
        self,
        *,
        authority: ProjectAuthority,
        current_epoch: int,
    ) -> int:
        """Remove old-epoch updates for one chat/project/repository owner.

        Current-epoch validation remains the actual security boundary. Cleanup
        merely prevents stale buffered events from accumulating indefinitely.
        """
        self._validate_actor(authority, current_epoch=current_epoch)
        doomed = [
            key
            for key, update in self._updates.items()
            if (
                update.authority.chat_id == authority.chat_id
                and update.authority.project_id == authority.project_id
                and update.authority.repo_scope == authority.repo_scope
                and update.authority.state_epoch != authority.state_epoch
            )
        ]
        for key in doomed:
            del self._updates[key]

        for stream_key in list(self._last_sequence):
            owner, _session_id = stream_key
            if (
                owner.chat_id == authority.chat_id
                and owner.project_id == authority.project_id
                and owner.repo_scope == authority.repo_scope
                and owner.state_epoch != authority.state_epoch
            ):
                del self._last_sequence[stream_key]

        return len(doomed)

    @staticmethod
    def _validate_actor(actor: ProjectAuthority, *, current_epoch: int) -> None:
        actor.validate()
        if actor.is_normal_chat:
            raise AuthorityError("normal chat cannot access builder update streams")
        require_current_epoch(actor, current_epoch=current_epoch)
