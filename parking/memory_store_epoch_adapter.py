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
MAX_TOTAL_TEXT_CHARS = 4_000_000
MAX_KEY_CHARS = 512
MAX_PROVENANCE_CHARS = 512
MAX_RECORDS_PER_AUTHORITY = 2_048


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    authority: MemoryAuthority
    key: str
    value: Any
    provenance: Mapping[str, Any]


def _snapshot_json(value: Any, *, depth: int = 0, budget: list[int] | None = None,
                   text_budget: list[int] | None = None) -> Any:
    """Copy bounded inert JSON data without invoking caller-defined hooks."""
    if budget is None:
        budget = [MAX_JSON_NODES]
    if text_budget is None:
        text_budget = [MAX_TOTAL_TEXT_CHARS]
    budget[0] -= 1
    if budget[0] < 0:
        raise MemoryAuthorityError("memory value exceeds node budget")
    if depth > MAX_JSON_DEPTH:
        raise MemoryAuthorityError("memory value nesting too deep")
    value_type = type(value)
    if value is None or value_type is bool:
        return value
    if value_type is int:
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise MemoryAuthorityError("memory numbers must be finite JSON numbers")
        return value
    if value_type is str:
        if len(value) > MAX_STRING_CHARS:
            raise MemoryAuthorityError("memory string too large")
        text_budget[0] -= len(value)
        if text_budget[0] < 0:
            raise MemoryAuthorityError("memory value exceeds aggregate text budget")
        return value
    if value_type is list:
        return [_snapshot_json(item, depth=depth + 1, budget=budget,
                               text_budget=text_budget) for item in value]
    if value_type is dict:
        out: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise MemoryAuthorityError("memory object keys must be plain strings")
            if len(key) > MAX_KEY_CHARS:
                raise MemoryAuthorityError("memory object key too large")
            text_budget[0] -= len(key)
            if text_budget[0] < 0:
                raise MemoryAuthorityError("memory value exceeds aggregate text budget")
            out[key] = _snapshot_json(item, depth=depth + 1, budget=budget,
                                      text_budget=text_budget)
        return out
    raise MemoryAuthorityError("memory value must be inert plain JSON-shaped data")


def _bounded_label(value: Any, *, field: str, limit: int) -> str:
    if type(value) is not str:
        raise MemoryAuthorityError(f"{field} must be a plain string")
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
        # Validate and detach the entire candidate before inspecting or mutating
        # existing state. A rejected write therefore cannot partially replace,
        # append, evict, or otherwise perturb previously trusted memory.
        auth = MemoryAuthority.parse(authority)
        clean_key = _bounded_label(key, field="memory key", limit=MAX_KEY_CHARS)
        if type(provenance) is not dict:
            raise MemoryAuthorityError("provenance must be a plain dict")
        required = {"source", "kind"}
        if set(provenance) != required:
            raise MemoryAuthorityError("provenance fields must be exactly source + kind")
        source = _bounded_label(provenance["source"], field="provenance source",
                                limit=MAX_PROVENANCE_CHARS)
        kind = _bounded_label(provenance["kind"], field="provenance kind",
                              limit=MAX_PROVENANCE_CHARS)
        clean_value = _snapshot_json(value)
        incoming = MemoryRecord(auth, clean_key, clean_value,
                                {"source": source, "kind": kind})

        matching = [i for i, record in enumerate(self._records)
                    if auth.permits(record.authority)]
        for index in matching:
            if self._records[index].key == clean_key:
                self._records[index] = incoming
                return
        if len(matching) >= MAX_RECORDS_PER_AUTHORITY:
            raise MemoryAuthorityError("project memory authority exceeds record budget")
        self._records.append(incoming)

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
