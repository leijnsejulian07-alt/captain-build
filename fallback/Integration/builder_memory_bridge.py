"""Fail-closed Captain Memory -> OpenBuilder context bridge.

The builder never becomes a second persistent memory store. It receives only
opaque references to Captain-owned project memory and resolves them at use time
against the current Project State authority. Any epoch/scope drift revokes the
bridge immediately.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from typing import Iterable

from builder_pane_snapshot import BuilderPaneSnapshot, assert_builder_pane_access
from project_memory_epoch import MemoryEnvelope, assert_memory_access

_MAX_MEMORY_REFS = 64


def _authority_digest(*, chat_id: str, project_id: str, repo_scope: str, state_epoch: int) -> str:
    raw = f"builder-memory\0{chat_id}\0{project_id}\0{repo_scope}\0{state_epoch}"
    return sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BuilderContextBridge:
    """Reference-only bridge; deliberately contains no project memory payloads."""

    memory_refs: tuple[str, ...]
    authority_digest: str

    def public_metadata(self) -> dict[str, object]:
        return {
            "memory_count": len(self.memory_refs),
            "authority_bound": True,
        }


def create_builder_context_bridge(
    memories: Iterable[MemoryEnvelope],
    pane: BuilderPaneSnapshot,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    state_epoch: int,
) -> BuilderContextBridge:
    """Bind Captain-owned project memory references to the current builder pane."""
    assert_builder_pane_access(
        pane,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        state_epoch=state_epoch,
    )

    refs: list[str] = []
    seen: set[str] = set()
    for memory in memories:
        if memory.scope != "project":
            raise PermissionError("builder context accepts project memory only")
        assert_memory_access(
            memory,
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            state_epoch=state_epoch,
        )
        if memory.memory_id in seen:
            raise ValueError("duplicate memory reference")
        seen.add(memory.memory_id)
        refs.append(memory.memory_id)
        if len(refs) > _MAX_MEMORY_REFS:
            raise ValueError("too many memory references")

    return BuilderContextBridge(
        memory_refs=tuple(refs),
        authority_digest=_authority_digest(
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            state_epoch=state_epoch,
        ),
    )


def resolve_builder_context(
    bridge: BuilderContextBridge,
    pane: BuilderPaneSnapshot,
    memories: Iterable[MemoryEnvelope],
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    state_epoch: int,
) -> tuple[tuple[str, dict[str, object]], ...]:
    """Resolve fresh Captain memory after re-validating current authority.

    Returned payloads are ephemeral copies for the active builder operation;
    callers must not persist them as builder-owned memory.
    """
    assert_builder_pane_access(
        pane,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        state_epoch=state_epoch,
    )
    expected = _authority_digest(
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        state_epoch=state_epoch,
    )
    if not compare_digest(bridge.authority_digest, expected):
        raise PermissionError("stale or foreign builder-memory bridge denied")

    indexed: dict[str, MemoryEnvelope] = {}
    for memory in memories:
        if memory.memory_id in indexed:
            raise ValueError("duplicate supplied memory id")
        indexed[memory.memory_id] = memory

    resolved: list[tuple[str, dict[str, object]]] = []
    for memory_id in bridge.memory_refs:
        memory = indexed.get(memory_id)
        if memory is None:
            raise PermissionError("referenced Captain memory unavailable")
        if memory.scope != "project":
            raise PermissionError("non-project memory cannot satisfy builder context")
        assert_memory_access(
            memory,
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            state_epoch=state_epoch,
        )
        resolved.append((memory.memory_id, dict(memory.payload)))

    return tuple(resolved)
