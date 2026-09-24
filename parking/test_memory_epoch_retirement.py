"""Regress stale-memory retirement on Project State epoch changes."""
from memory_authority import MemoryAuthorityError
from memory_persistence import snapshot
from memory_store_epoch_adapter import EpochBoundMemoryStore

H1 = "1" * 64
H2 = "2" * 64
OLD = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope_hash": H1, "state_epoch": 4}
NEW = {**OLD, "state_epoch": 5}
OTHER = {"chat_id": "chat-b", "project_id": "project-b", "repo_scope_hash": H2, "state_epoch": 9}
PROV = {"source": "captain", "kind": "user-confirmed"}


def rejected(store, previous, current):
    before = snapshot(store)
    try:
        store.advance_project_epoch(previous, current)
    except (MemoryAuthorityError, TypeError):
        assert snapshot(store) == before
        return
    raise AssertionError("unsafe epoch transition accepted")


def run():
    store = EpochBoundMemoryStore()
    store.write_project(OLD, key="old", value={"secret": "old-epoch"}, provenance=PROV)
    store.write_project(OTHER, key="other", value={"keep": True}, provenance=PROV)

    # Wrong direction, same epoch, or any authority-wall change must be atomic fail-closed.
    rejected(store, OLD, OLD)
    rejected(store, NEW, OLD)
    rejected(store, OLD, {**NEW, "chat_id": "chat-x"})
    rejected(store, OLD, {**NEW, "project_id": "project-x"})
    rejected(store, OLD, {**NEW, "repo_scope_hash": H2})

    class HostileDict(dict):
        called = False
        def __iter__(self):
            type(self).called = True
            raise AssertionError("hostile authority executed")
    rejected(store, HostileDict(OLD), NEW)
    assert HostileDict.called is False

    removed = store.advance_project_epoch(OLD, NEW)
    assert removed == 1
    assert store.build_context(OLD) == ()
    assert store.build_context(NEW) == ()  # stale memory is never auto-migrated.
    assert len(store.build_context(OTHER)) == 1

    persisted = snapshot(store)
    assert all(item["authority"] != OLD for item in persisted["records"])

    # Normal non-project behavior remains outside this project-memory adapter.
    # A fresh current epoch can receive new memory normally after retirement.
    store.write_project(NEW, key="new", value={"safe": True}, provenance=PROV)
    assert store.build_context(NEW)[0]["value"] == {"safe": True}
    print("PASS: project memory epoch retirement is scoped, atomic and non-migrating")


if __name__ == "__main__": run()
