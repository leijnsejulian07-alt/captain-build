from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from parking.integration.project_memory_context_epoch import MemoryContextRecord, ProjectStateEpoch
from parking.integration.scope_contract import ScopeKey, parse_scope


class MemoryContextStoreError(ValueError):
    pass


@dataclass(frozen=True)
class MemoryContextRef:
    kind: str
    record_id: str
    state_epoch: int


class ProjectMemoryContextStore:
    """Metadata-only index for epoch-bound Project Memory/context records.

    Captain remains the source of truth for memory/context payloads. This store tracks only
    authority metadata needed to authorize and eagerly revoke stale record references when
    Project State advances. It deliberately stores no memory text, prompts, embeddings,
    secrets, file contents, or provider payloads.
    """

    def __init__(self) -> None:
        self._records: dict[str, MemoryContextRecord] = {}

    def register(
        self,
        *,
        kind: str,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        state_epoch: int,
        record_id: str,
    ) -> MemoryContextRef:
        scope = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
        record = MemoryContextRecord(kind=kind, scope=scope, state_epoch=state_epoch, record_id=record_id)
        record.validate()
        existing = self._records.get(record_id)
        if existing is not None:
            if existing == record:
                return MemoryContextRef(kind=record.kind, record_id=record.record_id, state_epoch=record.state_epoch)
            raise MemoryContextStoreError("record_id already bound to different authority")
        self._records[record_id] = record
        return MemoryContextRef(kind=record.kind, record_id=record.record_id, state_epoch=record.state_epoch)

    def authorize(
        self,
        record_id: str,
        *,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        current_epoch: int,
    ) -> MemoryContextRef:
        if not isinstance(record_id, str) or not record_id:
            raise MemoryContextStoreError("invalid record_id")
        record = self._records.get(record_id)
        if record is None:
            raise PermissionError("memory/context record unavailable")
        active = ProjectStateEpoch.create(
            {"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope},
            current_epoch,
        )
        record.authorize(active, requesting_chat_id=chat_id)
        return MemoryContextRef(kind=record.kind, record_id=record.record_id, state_epoch=record.state_epoch)

    def revoke_stale_epochs(
        self,
        *,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        current_epoch: int,
    ) -> int:
        active = ProjectStateEpoch.create(
            {"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope},
            current_epoch,
        )
        stale_ids = [
            record_id
            for record_id, record in self._records.items()
            if record.scope == active.scope and record.state_epoch != current_epoch
        ]
        for record_id in stale_ids:
            del self._records[record_id]
        return len(stale_ids)

    def count_for_scope(self, scope: Mapping[str, object] | ScopeKey) -> int:
        parsed = parse_scope(scope)
        return sum(record.scope == parsed for record in self._records.values())
