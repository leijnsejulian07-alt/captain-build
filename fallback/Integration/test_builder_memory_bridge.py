from pathlib import Path
import sys

import pytest

FALLBACK = Path(__file__).resolve().parents[1]
for subdir in ("Memory", "Sandbox", "Integration"):
    path = str(FALLBACK / subdir)
    if path not in sys.path:
        sys.path.insert(0, path)

from builder_memory_bridge import create_builder_context_bridge, resolve_builder_context
from builder_pane_snapshot import project_builder_pane
from openbuilder_execution_flow import OpenBuilderExecution
from project_memory_epoch import build_memory
from sandbox_session_policy import create_sandbox_lease

AUTH = dict(chat_id="chat-a", project_id="project-a", repo_scope="repo-a", state_epoch=9)


def _pane(authority=AUTH):
    lease = create_sandbox_lease(session_id="sandbox-a", backend="local-test", **authority)
    return project_builder_pane(OpenBuilderExecution(lease=lease), **authority)


def _memory(memory_id="memory-a", authority=AUTH, text="source-of-truth"):
    return build_memory(
        memory_id=memory_id,
        kind="project_context",
        payload={"summary": text},
        **authority,
    )


def test_bridge_stores_only_refs_and_resolves_from_captain_memory():
    pane = _pane()
    memory = _memory()
    bridge = create_builder_context_bridge([memory], pane, **AUTH)

    assert bridge.memory_refs == ("memory-a",)
    assert "source-of-truth" not in repr(bridge)
    assert bridge.public_metadata() == {"memory_count": 1, "authority_bound": True}
    assert resolve_builder_context(bridge, pane, [memory], **AUTH) == (
        ("memory-a", {"summary": "source-of-truth"}),
    )


def test_epoch_rotation_revokes_bridge_and_stale_memory():
    pane = _pane()
    memory = _memory()
    bridge = create_builder_context_bridge([memory], pane, **AUTH)
    rotated = {**AUTH, "state_epoch": AUTH["state_epoch"] + 1}

    with pytest.raises(PermissionError):
        resolve_builder_context(bridge, pane, [memory], **rotated)


def test_cross_chat_project_or_repo_is_denied_fail_closed():
    pane = _pane()
    memory = _memory()
    bridge = create_builder_context_bridge([memory], pane, **AUTH)

    for foreign in (
        {**AUTH, "chat_id": "chat-b"},
        {**AUTH, "project_id": "project-b"},
        {**AUTH, "repo_scope": "repo-b"},
    ):
        with pytest.raises(PermissionError):
            resolve_builder_context(bridge, pane, [memory], **foreign)


def test_missing_or_replaced_memory_cannot_satisfy_reference():
    pane = _pane()
    memory = _memory()
    bridge = create_builder_context_bridge([memory], pane, **AUTH)

    with pytest.raises(PermissionError):
        resolve_builder_context(bridge, pane, [], **AUTH)

    foreign_auth = {**AUTH, "project_id": "project-b"}
    replacement = _memory(memory_id="memory-a", authority=foreign_auth, text="foreign")
    with pytest.raises(PermissionError):
        resolve_builder_context(bridge, pane, [replacement], **AUTH)


def test_builder_bridge_rejects_chat_or_global_memory():
    pane = _pane()
    chat_memory = build_memory(
        memory_id="chat-memory",
        kind="chat_context",
        payload={"summary": "ordinary chat"},
        chat_id=AUTH["chat_id"],
    )
    shared = build_memory(
        memory_id="shared-memory",
        kind="shared_learning",
        payload={"summary": "generic learning"},
    )

    for memory in (chat_memory, shared):
        with pytest.raises(PermissionError):
            create_builder_context_bridge([memory], pane, **AUTH)


def test_duplicate_and_excessive_references_are_rejected():
    pane = _pane()
    memory = _memory()
    with pytest.raises(ValueError):
        create_builder_context_bridge([memory, memory], pane, **AUTH)

    many = [_memory(memory_id=f"memory-{index}") for index in range(65)]
    with pytest.raises(ValueError):
        create_builder_context_bridge(many, pane, **AUTH)
