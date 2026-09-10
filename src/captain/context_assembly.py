"""Fail-closed Captain context assembly for model-facing prompt state.

Every memory/context record must cross this boundary before it may become
model context. The assembler deliberately re-validates backend results instead
of trusting a storage implementation to have filtered scopes correctly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Tuple

from .memory_context_store import EpochBoundMemoryContextStore, MemoryContextRecord
from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch


@dataclass(frozen=True)
class PromptContextItem:
    record_id: str
    kind: str
    payload: Mapping[str, object]
    provenance: str


@dataclass(frozen=True)
class PromptContextBundle:
    authority: ProjectAuthority
    current_epoch: Optional[int]
    items: Tuple[PromptContextItem, ...]


class ContextAssembler:
    """Assemble model-facing context without weakening Project State walls."""

    def __init__(
        self,
        store: EpochBoundMemoryContextStore,
        *,
        max_records: int = 64,
        max_scalar_chars: int = 64_000,
    ) -> None:
        if type(max_records) is not int or max_records <= 0:
            raise AuthorityError("max_records must be a positive integer")
        if type(max_scalar_chars) is not int or max_scalar_chars <= 0:
            raise AuthorityError("max_scalar_chars must be a positive integer")
        self._store = store
        self._max_records = max_records
        self._max_scalar_chars = max_scalar_chars

    def assemble(
        self,
        *,
        request: ProjectAuthority,
        current_epoch: Optional[int] = None,
        kinds: Optional[Iterable[str]] = None,
    ) -> PromptContextBundle:
        request.validate()
        if request.is_project_scope:
            if current_epoch is None:
                raise AuthorityError("project context assembly requires current_epoch")
            require_current_epoch(request, current_epoch=current_epoch)

        records = self._store.list_readable(
            request=request,
            current_epoch=current_epoch,
            kinds=kinds,
        )
        chosen: dict[tuple[str, str], tuple[int, MemoryContextRecord, str]] = {}
        for record in records:
            provenance, priority = self._validate_record(record, request=request)
            key = (record.kind, record.record_id)
            existing = chosen.get(key)
            if existing is None or priority > existing[0]:
                chosen[key] = (priority, record, provenance)
            elif priority == existing[0]:
                raise AuthorityError("ambiguous model-facing memory/context record")

        ordered = sorted(
            chosen.values(),
            key=lambda item: (-item[0], item[1].kind, item[1].record_id),
        )
        if len(ordered) > self._max_records:
            raise AuthorityError("model context record budget exceeded")

        scalar_chars = 0
        items = []
        for _, record, provenance in ordered:
            scalar_chars += self._validate_payload(record.payload)
            if scalar_chars > self._max_scalar_chars:
                raise AuthorityError("model context scalar budget exceeded")
            items.append(
                PromptContextItem(
                    record_id=record.record_id,
                    kind=record.kind,
                    payload=record.payload,
                    provenance=provenance,
                )
            )

        return PromptContextBundle(
            authority=request,
            current_epoch=current_epoch,
            items=tuple(items),
        )

    @staticmethod
    def _validate_record(
        record: MemoryContextRecord,
        *,
        request: ProjectAuthority,
    ) -> tuple[str, int]:
        record.scope.authority.validate()
        if not record.scope.readable_by(request):
            raise AuthorityError("backend returned unauthorized model context")

        if request.is_normal_chat:
            if not record.scope.authority.is_normal_chat:
                raise AuthorityError("project state cannot enter normal chat context")
            return "normal_chat", 2

        if record.scope.authority.is_normal_chat:
            if not record.scope.generic or record.scope.project_specific:
                raise AuthorityError("unsafe global memory cannot enter project context")
            return "generic_global", 1

        request.require_same_owner(record.scope.authority)
        return "current_project_epoch", 2

    @classmethod
    def _validate_payload(cls, payload: Mapping[str, object]) -> int:
        if not isinstance(payload, Mapping):
            raise AuthorityError("model context payload must be a mapping")
        return cls._count_mapping(payload, path="$")

    @classmethod
    def _count_mapping(cls, value: Mapping[str, object], *, path: str) -> int:
        total = 0
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise AuthorityError(f"invalid model context key at {path}")
            total += len(key)
            total += cls._count_value(nested, path=f"{path}.{key}")
        return total

    @classmethod
    def _count_value(cls, value: object, *, path: str) -> int:
        if value is None:
            return 0
        if isinstance(value, (str, bool, int, float)):
            return len(str(value))
        if isinstance(value, Mapping):
            return cls._count_mapping(value, path=path)
        if type(value) is tuple:
            return sum(cls._count_value(item, path=f"{path}[]") for item in value)
        raise AuthorityError(
            f"unsupported model context value at {path}: {type(value).__name__}"
        )
