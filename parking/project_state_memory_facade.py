"""Project-State-owned facade for Captain project memory.

Plugins/builders never choose a memory authority through this surface. Captain resolves
the current Project State and passes that canonical authority into each operation; the
underlying epoch store remains an implementation detail.
"""
from __future__ import annotations

from typing import Any, Mapping

from memory_authority import MemoryAuthority, MemoryAuthorityError
from memory_store_epoch_adapter import EpochBoundMemoryStore, MemoryRecord


class ProjectStateMemoryFacade:
    """Stamp writes from trusted current state and keep stale epochs fail-closed."""

    def __init__(self, store: EpochBoundMemoryStore | None = None) -> None:
        if store is not None and type(store) is not EpochBoundMemoryStore:
            raise MemoryAuthorityError("memory store must be the native epoch-bound store")
        self.__store = store if store is not None else EpochBoundMemoryStore()

    @staticmethod
    def _canonical(current: Mapping[str, Any]) -> dict[str, Any]:
        auth = MemoryAuthority.parse(current)
        return {
            "chat_id": auth.chat_id,
            "project_id": auth.project_id,
            "repo_scope_hash": auth.repo_scope_hash,
            "state_epoch": auth.state_epoch,
        }

    def write_current(self, current: Mapping[str, Any], *, key: str, value: Any,
                      provenance: Mapping[str, Any]) -> None:
        """Write only under Captain's current authority; caller cannot claim another epoch."""
        canonical = self._canonical(current)
        self.__store.write_project(canonical, key=key, value=value, provenance=provenance)

    def read_current(self, current: Mapping[str, Any]) -> tuple[MemoryRecord, ...]:
        try:
            canonical = self._canonical(current)
        except (MemoryAuthorityError, TypeError):
            return ()
        return self.__store.read_project(canonical)

    def build_current_context(self, current: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
        try:
            canonical = self._canonical(current)
        except (MemoryAuthorityError, TypeError):
            return ()
        return self.__store.build_context(canonical)

    def advance(self, previous: Mapping[str, Any], current: Mapping[str, Any]) -> int:
        """Apply a trusted Project State advance and retire all older same-scope memory."""
        old = self._canonical(previous)
        new = self._canonical(current)
        return self.__store.advance_project_epoch(old, new)

    def snapshot_store_for_persistence(self) -> EpochBoundMemoryStore:
        """Trusted Captain persistence hook; do not expose this object to plugins/builders."""
        return self.__store
