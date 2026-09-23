"""Regressions for the epoch-bound project memory/context adapter."""
from memory_authority import MemoryAuthorityError
from memory_store_epoch_adapter import EpochBoundMemoryStore

H1 = "1" * 64
H2 = "2" * 64
BASE = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope_hash": H1, "state_epoch": 4}


def changed(field, value):
    result = dict(BASE)
    result[field] = value
    return result


def run():
    store = EpochBoundMemoryStore()
    provenance = {"source": "captain", "kind": "user-confirmed"}
    store.write_project(BASE, key="decision", value="use adapter", provenance=provenance)

    visible = store.read_project(BASE)
    assert len(visible) == 1
    assert visible[0].value == "use adapter"
    assert visible[0].provenance == provenance
    assert store.build_context(BASE) == (
        {"key": "decision", "value": "use adapter", "provenance": provenance},
    )

    # Exact wall: stale memory AND context disappear after any authority change.
    for field, value in (
        ("state_epoch", 5),
        ("chat_id", "chat-b"),
        ("project_id", "project-b"),
        ("repo_scope_hash", H2),
    ):
        current = changed(field, value)
        assert store.read_project(current) == (), field
        assert store.build_context(current) == (), field

    # Fail closed on malformed current Project State.
    assert store.read_project({**BASE, "state_epoch": 0}) == ()
    assert store.read_project({**BASE, "state_epoch": True}) == ()
    assert store.read_project({**BASE, "repo_scope_hash": "raw/path"}) == ()
    assert store.build_context({"chat_id": "ordinary-chat", "message": "hello"}) == ()

    # Writes never silently fall back to global/non-project memory.
    try:
        store.write_project({"chat_id": "ordinary-chat"}, key="x", value=1, provenance={})
    except MemoryAuthorityError:
        pass
    else:
        raise AssertionError("malformed project-memory write must fail closed")

    # Old record remains physically present for retention/migration, but cannot leak
    # through current reads/context after epoch rollover.
    assert len(tuple(store.all_records_for_test_only())) == 1
    print("PASS: project memory read/write/context are epoch-bound and fail-closed")


if __name__ == "__main__":
    run()
