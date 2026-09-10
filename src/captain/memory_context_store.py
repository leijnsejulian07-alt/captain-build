"""Epoch-bound in-memory Project Memory/context store.

This deliberately small runtime primitive makes the ProjectAuthority boundary
concrete for Captain memory/context code without coupling storage to a specific
DB, vector store, model, or UI. Durable backends can implement the same contract.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .project_authority import (
    AuthorityError,
    ProjectAuthority,
    ScopedRecord,
    require_current_epoch,
)


@dataclass(frozen=True)
class MemoryContextRecord:
    record_id: str
    kind: str
    payload: Mapping[str, object]
    scope: ScopedRecord

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or not self.record_id.strip():
            raise AuthorityError("record_id must be a non-empty string")
        if self.kind not in {"memory", "context"}:
            raise AuthorityError("kind must be memory or context")
        if not isinstance(self.payload, Mapping):
            raise AuthorityError("payload must be a mapping")


AuthorityStorageKey = Tuple[Optional[str], Optional[str], Optional[str], Optional[int], str]


def _freeze_payload_value(value: object, *, path: str = "$") -> object:
    """Create an immutable, deterministic snapshot without invoking deepcopy hooks.

    Memory/context is an authority boundary. Holding caller-owned mutable objects
    after a successful authorization check would let later code mutate persisted
    state without passing through that check again. Restricting snapshots to
    JSON-like builtins also avoids executing arbitrary ``__deepcopy__`` methods
    from plugin/provider objects at this boundary.
    """

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AuthorityError(f"payload contains non-finite float at {path}")
        return value
    if type(value) is dict:
        frozen: Dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise AuthorityError(f"payload keys must be non-empty strings at {path}")
            frozen[key] = _freeze_payload_value(nested, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if type(value) in {list, tuple}:
        return tuple(
            _freeze_payload_value(nested, path=f"{path}[{index}]")
            for index, nested in enumerate(value)
        )
    raise AuthorityError(
        f"payload contains unsupported mutable/custom value at {path}: {type(value).__name__}"
    )


def _snapshot_record(record: MemoryContextRecord) -> MemoryContextRecord:
    payload = _freeze_payload_value(dict(record.payload))
    assert isinstance(payload, Mapping)
    return MemoryContextRecord(
        record_id=record.record_id,
        kind=record.kind,
        payload=payload,
        scope=record.scope,
    )


class EpochBoundMemoryContextStore:
    """Fail-closed store for Captain memory/context records.

    Every project-scoped read/write is checked against the caller's active
    Project State epoch. Normal non-project chat remains supported, but project
    records never degrade to normal-chat/global visibility. Explicitly global,
    distilled, non-project-specific records can be read from project scope.

    Record identity is authority-scoped rather than globally keyed by record_id.
    This is important because otherwise an unrelated project, a later Project
    State epoch, or normal chat could overwrite another scope's record merely by
    choosing the same logical record id.

    Payloads are snapshotted into immutable builtin containers at write time so
    post-write caller mutation cannot alter stored memory outside authority
    checks. Unsupported custom/mutable payload objects fail closed.
    """

    def __init__(self) -> None:
        self._records: Dict[AuthorityStorageKey, MemoryContextRecord] = {}

    @staticmethod
    def _storage_key(authority: ProjectAuthority, record_id: str) -> AuthorityStorageKey:
        authority.validate()
        return (
            authority.chat_id,
            authority.project_id,
            authority.repo_scope,
            authority.state_epoch,
            record_id,
        )

    def put(
        self,
        record: MemoryContextRecord,
        *,
        actor: ProjectAuthority,
        current_epoch: Optional[int] = None,
    ) -> None:
        actor.validate()
        record.scope.authority.validate()

        if actor.is_normal_chat:
            if not record.scope.authority.is_normal_chat:
                raise AuthorityError("normal chat cannot write project-scoped state")
        else:
            if current_epoch is None:
                raise AuthorityError("project writes require the active current_epoch")
            require_current_epoch(actor, current_epoch=current_epoch)
            actor.require_same_owner(record.scope.authority)

        key = self._storage_key(record.scope.authority, record.record_id)
        self._records[key] = _snapshot_record(record)

    def get(
        self,
        record_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: Optional[int] = None,
    ) -> Optional[MemoryContextRecord]:
        self._validate_read_authority(request, current_epoch=current_epoch)
        if not isinstance(record_id, str) or not record_id.strip():
            raise AuthorityError("record_id must be a non-empty string")

        # Exact-owner state always wins over generic global learning with the
        # same logical id. Stale epochs and other projects cannot become a
        # fallback because readable_by() remains the final fail-closed gate.
        exact = self._records.get(self._storage_key(request, record_id))
        if exact is not None and exact.scope.readable_by(request):
            return exact

        readable = [
            record
            for record in self._records.values()
            if record.record_id == record_id and record.scope.readable_by(request)
        ]
        if not readable:
            return None
        if len(readable) > 1:
            # Multiple readable fallback records with the same logical id are
            # ambiguous. Refuse to guess rather than selecting cross-scope state
            # by insertion order.
            raise AuthorityError("ambiguous readable memory/context record_id")
        return readable[0]

    def list_readable(
        self,
        *,
        request: ProjectAuthority,
        current_epoch: Optional[int] = None,
        kinds: Optional[Iterable[str]] = None,
    ) -> List[MemoryContextRecord]:
        self._validate_read_authority(request, current_epoch=current_epoch)
        allowed_kinds = None if kinds is None else set(kinds)
        if allowed_kinds is not None and not allowed_kinds <= {"memory", "context"}:
            raise AuthorityError("unsupported memory/context kind")
        return [
            record
            for record in self._records.values()
            if (allowed_kinds is None or record.kind in allowed_kinds)
            and record.scope.readable_by(request)
        ]

    @staticmethod
    def _validate_read_authority(
        request: ProjectAuthority,
        *,
        current_epoch: Optional[int],
    ) -> None:
        request.validate()
        if request.is_normal_chat:
            return
        if current_epoch is None:
            raise AuthorityError("project reads require the active current_epoch")
        require_current_epoch(request, current_epoch=current_epoch)
