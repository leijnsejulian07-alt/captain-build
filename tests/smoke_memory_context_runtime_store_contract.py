"""Regression contract for epoch-bound Project Memory/context runtime storage."""

from src.captain.memory_context_store import (
    EpochBoundMemoryContextStore,
    MemoryContextRecord,
)
from src.captain.project_authority import AuthorityError, ProjectAuthority, ScopedRecord


def expect_denied(fn) -> None:
    try:
        fn()
    except AuthorityError:
        return
    raise AssertionError("expected fail-closed AuthorityError")


def rec(record_id, kind, payload, authority, *, generic=False, project_specific=True):
    return MemoryContextRecord(
        record_id=record_id,
        kind=kind,
        payload=payload,
        scope=ScopedRecord(
            authority=authority,
            generic=generic,
            project_specific=project_specific,
        ),
    )


def main() -> None:
    store = EpochBoundMemoryContextStore()

    normal = ProjectAuthority()
    a7 = ProjectAuthority("chat-a", "project-a", "owner/repo-a", 7)
    a8 = ProjectAuthority("chat-a", "project-a", "owner/repo-a", 8)
    b7 = ProjectAuthority("chat-b", "project-b", "owner/repo-b", 7)

    # Normal chat remains useful and can retain/read normal-chat context.
    store.put(rec("global-chat", "context", {"tone": "concise"}, normal), actor=normal)
    assert store.get("global-chat", request=normal).payload["tone"] == "concise"

    # Project state must be written with matching owner and active epoch.
    store.put(rec("a-memory", "memory", {"secret": "project-a"}, a7), actor=a7, current_epoch=7)
    assert store.get("a-memory", request=a7, current_epoch=7) is not None

    expect_denied(lambda: store.put(rec("stale-write", "memory", {}, a7), actor=a7, current_epoch=8))
    expect_denied(lambda: store.put(rec("cross-write", "memory", {}, b7), actor=a7, current_epoch=7))
    expect_denied(lambda: store.put(rec("normal-cross", "memory", {}, a7), actor=normal))

    # After epoch change, stale memory/context becomes inaccessible even if still persisted.
    expect_denied(lambda: store.get("a-memory", request=a7, current_epoch=8))
    assert store.get("a-memory", request=a8, current_epoch=8) is None

    # Cross-project/repo/chat reads are denied by invisibility rather than data leakage.
    assert store.get("a-memory", request=b7, current_epoch=7) is None
    assert store.get("a-memory", request=normal) is None

    # Safe distilled global learning is explicitly readable from project scope.
    store.put(
        rec(
            "generic-learning",
            "memory",
            {"lesson": "prefer deterministic tests"},
            normal,
            generic=True,
            project_specific=False,
        ),
        actor=normal,
    )
    assert store.get("generic-learning", request=a7, current_epoch=7) is not None

    # Raw normal-chat/project-specific state is not implicitly injected into projects.
    assert store.get("global-chat", request=a7, current_epoch=7) is None

    # Listing obeys the same wall and type filter.
    readable = store.list_readable(request=a7, current_epoch=7, kinds=["memory"])
    ids = {item.record_id for item in readable}
    assert ids == {"a-memory", "generic-learning"}
    expect_denied(lambda: store.list_readable(request=a7, current_epoch=8))
    expect_denied(lambda: store.list_readable(request=a7, current_epoch=7, kinds=["preview"]))

    print("MEMORY_CONTEXT_RUNTIME_STORE_EPOCH_PASS")


if __name__ == "__main__":
    main()
