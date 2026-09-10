from __future__ import annotations

from math import nan

import pytest

from src.captain.memory_context_store import (
    EpochBoundMemoryContextStore,
    MemoryContextRecord,
)
from src.captain.project_authority import AuthorityError, ProjectAuthority, ScopedRecord


def project(epoch: int = 3) -> ProjectAuthority:
    return ProjectAuthority(
        chat_id="chat-a",
        project_id="project-a",
        repo_scope="owner/repo",
        state_epoch=epoch,
    )


def test_post_write_mutation_cannot_change_stored_payload() -> None:
    authority = project()
    store = EpochBoundMemoryContextStore()
    source = {
        "goal": "ship",
        "nested": {"phase": "plan"},
        "items": ["a", "b"],
    }
    record = MemoryContextRecord(
        record_id="state",
        kind="memory",
        payload=source,
        scope=ScopedRecord(authority),
    )

    store.put(record, actor=authority, current_epoch=3)
    source["goal"] = "tampered"
    source["nested"]["phase"] = "tampered"
    source["items"].append("tampered")

    stored = store.get("state", request=authority, current_epoch=3)
    assert stored is not None
    assert stored.payload["goal"] == "ship"
    assert stored.payload["nested"]["phase"] == "plan"
    assert stored.payload["items"] == ("a", "b")


def test_returned_payload_is_deeply_immutable() -> None:
    authority = project()
    store = EpochBoundMemoryContextStore()
    store.put(
        MemoryContextRecord(
            record_id="ctx",
            kind="context",
            payload={"nested": {"answer": 42}, "items": [1, 2]},
            scope=ScopedRecord(authority),
        ),
        actor=authority,
        current_epoch=3,
    )

    stored = store.get("ctx", request=authority, current_epoch=3)
    assert stored is not None
    with pytest.raises(TypeError):
        stored.payload["new"] = "nope"  # type: ignore[index]
    with pytest.raises(TypeError):
        stored.payload["nested"]["answer"] = 7  # type: ignore[index]
    assert stored.payload["items"] == (1, 2)


def test_custom_payload_objects_fail_closed_without_copy_hooks() -> None:
    authority = project()
    store = EpochBoundMemoryContextStore()

    class Hostile:
        copied = False

        def __deepcopy__(self, memo: object) -> "Hostile":
            Hostile.copied = True
            raise AssertionError("must not execute plugin deepcopy hooks")

    with pytest.raises(AuthorityError, match="unsupported mutable/custom value"):
        store.put(
            MemoryContextRecord(
                record_id="hostile",
                kind="memory",
                payload={"plugin_object": Hostile()},
                scope=ScopedRecord(authority),
            ),
            actor=authority,
            current_epoch=3,
        )
    assert Hostile.copied is False


def test_non_finite_floats_fail_closed() -> None:
    authority = project()
    store = EpochBoundMemoryContextStore()
    with pytest.raises(AuthorityError, match="non-finite float"):
        store.put(
            MemoryContextRecord(
                record_id="nan",
                kind="context",
                payload={"score": nan},
                scope=ScopedRecord(authority),
            ),
            actor=authority,
            current_epoch=3,
        )


def test_normal_chat_still_accepts_safe_memory() -> None:
    normal = ProjectAuthority()
    store = EpochBoundMemoryContextStore()
    source = {"preference": ["concise", "useful"]}
    store.put(
        MemoryContextRecord(
            record_id="normal-pref",
            kind="memory",
            payload=source,
            scope=ScopedRecord(normal, generic=True, project_specific=False),
        ),
        actor=normal,
    )
    source["preference"].append("tampered")

    stored = store.get("normal-pref", request=normal)
    assert stored is not None
    assert stored.payload["preference"] == ("concise", "useful")
