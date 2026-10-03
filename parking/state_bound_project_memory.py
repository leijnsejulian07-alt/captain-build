"""Captain-owned live Project State boundary for project memory/context.

This wrapper is the public runtime surface. Callers never provide memory authority:
Captain resolves it immediately before every operation.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from memory_authority import MemoryAuthority, MemoryAuthorityError
from project_state_memory_facade import ProjectStateMemoryFacade


class StateBoundProjectMemory:
    """Bind memory/context access to Captain's live Project State resolver."""

    def __init__(
        self,
        resolve_current: Callable[[], Mapping[str, Any]],
        facade: ProjectStateMemoryFacade | None = None,
    ) -> None:
        if not callable(resolve_current):
            raise TypeError("resolve_current must be callable")
        self.__resolve_current = resolve_current
        self.__facade = facade if facade is not None else ProjectStateMemoryFacade()
        self.__last_by_scope: dict[tuple[str, str, str], dict[str, Any]] = {}

    @staticmethod
    def _canonical(current: Mapping[str, Any]) -> dict[str, Any]:
        auth = MemoryAuthority.parse(current)
        return {
            "chat_id": auth.chat_id,
            "project_id": auth.project_id,
            "repo_scope_hash": auth.repo_scope_hash,
            "state_epoch": auth.state_epoch,
        }

    def _resolve(self) -> dict[str, Any]:
        current = self._canonical(self.__resolve_current())
        scope = (
            current["chat_id"],
            current["project_id"],
            current["repo_scope_hash"],
        )
        previous = self.__last_by_scope.get(scope)
        if previous is not None:
            if current["state_epoch"] < previous["state_epoch"]:
                raise MemoryAuthorityError("live Project State epoch regressed")
            if current["state_epoch"] > previous["state_epoch"]:
                self.__facade.advance(previous, current)
        self.__last_by_scope[scope] = current
        return current

    def write(self, *, key: str, value: Any, provenance: Mapping[str, Any]) -> None:
        current = self._resolve()
        self.__facade.write_current(current, key=key, value=value, provenance=provenance)

    def read(self):
        try:
            current = self._resolve()
        except (MemoryAuthorityError, TypeError, KeyError):
            return ()
        return self.__facade.read_current(current)

    def build_context(self) -> tuple[dict[str, Any], ...]:
        try:
            current = self._resolve()
        except (MemoryAuthorityError, TypeError, KeyError):
            return ()
        return self.__facade.build_current_context(current)

    def snapshot_for_persistence(self) -> dict[str, Any]:
        return self.__facade.snapshot_for_persistence()
