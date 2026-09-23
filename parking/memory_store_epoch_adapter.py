"""Reference adapter for Captain project memory/context isolation.

Parking implementation only: in-memory, dependency-free, no network or secrets.
Captain remains source of truth; this demonstrates the read/write boundary that
native or OSS memory providers must preserve.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from memory_authority import MemoryAuthority, MemoryAuthorityError

MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 10_000
MAX_STRING_CHARS = 1_000_000
MAX_KEY_CHARS = 512
MAX_PROVENANCE_CHARS = 512


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    authority: MemoryAuthority
    key: str
    value: Any
    provenance: Mapping[str, Any]


def _snapshot_json(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> Any:
    """Copy bounded inert JSON data without invoking caller-defined hooks."""
    if budget is None:
        budget = [MAX_JSON_NODES]
    budget[0] -= 1
    if budget[0] < 0:
        raise MemoryAuthorityError("memory value exceeds node budget")
    if depth > MAX_JSON_DEPTH:
        raise MemoryAuthorityError("memory value nesting too deep")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MemoryAuthorityError("memory numbers must be finite JSON numbers")
        return value
    if isinstance(value, str):
        if len(value) > MAX_STRING_CHARS:
            raise MemoryAuthorityError("memory string too large")
        return value
    if isinstance(value, list):
        return [_snapshot_json(item, depth=depth + 1, budget=budget) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise MemoryAuthorityError("memory object keys must be strings")
            if len(key) > MAX_KEY_CHARS:
                raise MemoryAuthorityError("memory object key too large")
            out[key] = _snapshot_json(item, depth=depth + 1, budget=budget)
        return out
    raise MemoryAuthorityError("memory value must be inert JSON-shaped data")


def _bounded_label(value: Any, *, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise MemoryAuthorityError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise MemoryAuthorityError(f"{field} required")
    if len(normalized) > limit:
        raise MemoryAuthorityError(f"{field} too large")
    return normalized


class EpochBoundMemoryStore:
    def __init__(self) -> None:
        self._records: list[MemoryRecord] = []

    def write_project(self, authority: Mapping[str, Any], *, key: str, value: Any,
                      provenance: Mapping[str, Any]) -> None:
        auth = MemoryAuthority.parse(authority)
        clean_key = _bounded_label(key, field="memory key", limit=MAX_KEY_CHARS)
        if not isinstance(provenance, Mapping):
            raise MemoryAuthorityError("provenance mapping required")
        required = {"source", "kind"}
        if set(provenance) != required:
            raise MemoryAuthorityError("provenance fields must be exactly source + kind")
        source = _bounded_label(provenance["source"], field="provenance source",
                                limit=MAX_PROVENANCE_CHARS)
        kind = _bounded_label(provenance["kind"], field="provenance kind",
                              limit=MAX_PROVENANCE_CHARS)
        self._records.append(MemoryRecord(auth, clean_key, _snapshot_json(value),
                                          {"source": source, "kind": kind}))

    def read_project(self, current: Mapping[str, Any]) -> tuple[MemoryRecord, ...]:
        """Return detached records with exact current authority; malformed state fails closed."""
        try:
            auth = MemoryAuthority.parse(current)
        except (MemoryAuthorityError, TypeError):
            return ()
        return tuple(MemoryRecord(record.authority, record.key, _snapshot_json(record.value),
                                  dict(record.provenance))
                     for record in self._records if auth.permits(record.authority))

    def build_context(self, current: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
        """Context assembly uses the same authority gate and returns detached values."""
        return tuple({"key": record.key, "value": _snapshot_json(record.value),
                      "provenance": dict(record.provenance)}
                     for record in self.read_project(current))

    def all_records_for_test_only(self) -> Iterable[MemoryRecord]:
        return tuple(self._records)
