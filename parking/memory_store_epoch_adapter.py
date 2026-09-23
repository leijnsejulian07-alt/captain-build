"""Reference adapter for Captain project memory/context isolation.

Parking implementation only: in-memory, dependency-free, no network or secrets.
Captain remains source of truth; this demonstrates the read/write boundary that
native or OSS memory providers must preserve.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from memory_authority import MemoryAuthority, MemoryAuthorityError


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    authority: MemoryAuthority
    key: str
    value: Any
    provenance: Mapping[str, Any]


class EpochBoundMemoryStore:
    def __init__(self) -> None:
        self._records: list[MemoryRecord] = []

    def write_project(
        self,
        authority: Mapping[str, Any],
        *,
        key: str,
        value: Any,
        provenance: Mapping[str, Any],
    ) -> None:
        auth = MemoryAuthority.parse(authority)
        if not isinstance(key, str) or not key.strip():
            raise MemoryAuthorityError("memory key required")
        if not isinstance(provenance, Mapping):
            raise MemoryAuthorityError("provenance mapping required")
        self._records.append(MemoryRecord(auth, key.strip(), value, dict(provenance)))

    def read_project(self, current: Mapping[str, Any]) -> tuple[MemoryRecord, ...]:
        """Return only records with exact current authority; malformed current state fails closed."""
        try:
            auth = MemoryAuthority.parse(current)
        except (MemoryAuthorityError, TypeError):
            return ()
        return tuple(record for record in self._records if auth.permits(record.authority))

    def build_context(self, current: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
        """Context assembly uses the same authority gate as direct memory reads."""
        return tuple(
            {"key": record.key, "value": record.value, "provenance": dict(record.provenance)}
            for record in self.read_project(current)
        )

    def all_records_for_test_only(self) -> Iterable[MemoryRecord]:
        return tuple(self._records)
