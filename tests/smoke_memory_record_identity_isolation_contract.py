"""Regression contract for authority-scoped Project Memory/context record identity."""

from src.captain.memory_context_store import EpochBoundMemoryContextStore, MemoryContextRecord
from src.captain.project_authority import AuthorityError, ProjectAuthority, ScopedRecord


def rec(record_id, value, authority, *, generic=False, project_specific=True):
    return MemoryContextRecord(
        record_id=record_id,
        kind="memory",
        payload={"value": value},
        scope=ScopedRecord(
            authority=authority,
            generic=generic,
            project_specific=project_specific,
        ),
    )


def expect_denied(fn) -> None:
    try:
        fn()
    except AuthorityError:
        return
    raise AssertionError("expected fail-closed AuthorityError")


def main() -> None:
    store = EpochBoundMemoryContextStore()
    normal = ProjectAuthority()
    a7 = ProjectAuthority("chat-a", "project-a", "owner/repo-a", 7)
    a8 = ProjectAuthority("chat-a", "project-a", "owner/repo-a", 8)
    b7 = ProjectAuthority("chat-b", "project-b", "owner/repo-b", 7)

    # The same logical id may exist safely in unrelated projects without either
    # project overwriting the other's state.
    store.put(rec("shared-id", "a7", a7), actor=a7, current_epoch=7)
    store.put(rec("shared-id", "b7", b7), actor=b7, current_epoch=7)
    assert store.get("shared-id", request=a7, current_epoch=7).payload["value"] == "a7"
    assert store.get("shared-id", request=b7, current_epoch=7).payload["value"] == "b7"

    # An epoch transition may reuse a logical id while stale state remains
    # persisted. The new epoch sees only its own state; the old epoch cannot be
    # resurrected by asking with the new active epoch.
    store.put(rec("shared-id", "a8", a8), actor=a8, current_epoch=8)
    assert store.get("shared-id", request=a8, current_epoch=8).payload["value"] == "a8"
    expect_denied(lambda: store.get("shared-id", request=a7, current_epoch=8))

    # Normal chat cannot clobber project state by choosing the same record id.
    store.put(rec("shared-id", "normal", normal), actor=normal)
    assert store.get("shared-id", request=normal).payload["value"] == "normal"
    assert store.get("shared-id", request=a8, current_epoch=8).payload["value"] == "a8"
    assert store.get("shared-id", request=b7, current_epoch=7).payload["value"] == "b7"

    # Generic global learning with a colliding id remains only a fallback. Exact
    # project state must win deterministically for a project request.
    store.put(
        rec(
            "priority-id",
            "generic",
            normal,
            generic=True,
            project_specific=False,
        ),
        actor=normal,
    )
    store.put(rec("priority-id", "project-a", a8), actor=a8, current_epoch=8)
    assert store.get("priority-id", request=a8, current_epoch=8).payload["value"] == "project-a"
    assert store.get("priority-id", request=b7, current_epoch=7).payload["value"] == "generic"

    # Two globally readable fallback records with the same id are impossible in
    # this store because normal-chat authority + record_id is one storage key;
    # updating it remains a same-scope replacement, not a cross-project write.
    store.put(
        rec(
            "priority-id",
            "generic-v2",
            normal,
            generic=True,
            project_specific=False,
        ),
        actor=normal,
    )
    assert store.get("priority-id", request=b7, current_epoch=7).payload["value"] == "generic-v2"
    assert store.get("priority-id", request=a8, current_epoch=8).payload["value"] == "project-a"

    readable_a8 = {(item.record_id, item.payload["value"]) for item in store.list_readable(request=a8, current_epoch=8)}
    assert ("shared-id", "a8") in readable_a8
    assert ("shared-id", "a7") not in readable_a8
    assert ("shared-id", "b7") not in readable_a8

    print("MEMORY_RECORD_IDENTITY_ISOLATION_PASS")


if __name__ == "__main__":
    main()
