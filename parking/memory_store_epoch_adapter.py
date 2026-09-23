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


def _snapshot_json(value: Any, *, depth: int = 0) -> Any:
    """Copy only inert JSON-shaped values; never invoke caller-defined copy hooks."""
    if depth > 32:
        raise MemoryAuthorityError("memory value nesting too deep")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_snapshot_json(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise MemoryAuthorityError("memory object keys must be strings")
            out[key] = _snapshot_json(item, depth=depth + 1)
        return out
    raise MemoryAuthorityError("memory value must be inert JSON-shaped data")


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
        required = {"source", "kind"}
        if set(provenance) != required:
            raise MemoryAuthorityError("provenance fields must be exactly source + kind")
        source = provenance["source"]
        kind = provenance["kind"]
        if not isinstance(source, str) or not source.strip():
            raise MemoryAuthorityError("provenance source required")
        if not isinstance(kind, str) or not kind.strip():
            raise MemoryAuthorityError("provenance kind required")
        self._records.append(
            MemoryRecord(
                auth,
                key.strip(),
                _snapshot_json(value),
                {"source": source.strip(), "kind": kind.strip()},
            )
        )

    def read_project(self, current: Mapping[str, Any]) -> tuple[MemoryRecord, ...]:
        """Return detached records with exact current authority; malformed state fails closed."""
        try:
            auth = MemoryAuthority.parse(current)
        except (MemoryAuthorityError, TypeError):
            return ()
        return tuple(
            MemoryRecord(
                record.authority,
                record.key,
                _snapshot_json(record.value),
                dict(record.provenance),
            )
            for record in self._records
            if auth.permits(record.authority)
        )

    def build_context(self, current: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
        """Context assembly uses the same authority gate and returns detached values."""
        return tuple(
            {"key": record.key, "value": _snapshot_json(record.value), "provenance": dict(record.provenance)}
            for record in self.read_project(current)
        )

    def all_records_for_test_only(self) -> Iterable[MemoryRecord]:
        return tuple(self._records)
