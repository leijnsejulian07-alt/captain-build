"""Regress stale-memory retirement on Project State epoch changes."""
from memory_authority import MemoryAuthorityError
from memory_persistence import snapshot
from memory_store_epoch_adapter import EpochBoundMemoryStore

H1 = "1" * 64
H2 = "2" * 64
OLD = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope_hash": H1, "state_epoch": 4}
MID = {**OLD, "state_epoch": 5}
NEW = {**OLD, "state_epoch": 6}
FUTURE = {**OLD, "state_epoch": 7}
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
    store.write_project(MID, key="missed", value={"secret": "missed-epoch"}, provenance=PROV)
    store.write_project(FUTURE, key="future", value={"keep": "future"}, provenance=PROV)
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

    # A 4 -> 6 jump must retire both epoch 4 and any stranded epoch 5 memory.
    removed = store.advance_project_epoch(OLD, NEW)
    assert removed == 2
    assert store.build_context(OLD) == ()
    assert store.build_context(MID) == ()
    assert store.build_context(NEW) == ()  # stale memory is never auto-migrated.
    assert store.build_context(FUTURE)[0]["value"] == {"keep": "future"}
    assert len(store.build_context(OTHER)) == 1

    persisted = snapshot(store)
    stale = {4, 5}
    assert all(not (item["authority"]["chat_id"] == OLD["chat_id"]
                       and item["authority"]["project_id"] == OLD["project_id"]
                       and item["authority"]["repo_scope_hash"] == H1
                       and item["authority"]["state_epoch"] in stale)
               for item in persisted["records"])

    store.write_project(NEW, key="new", value={"safe": True}, provenance=PROV)
    assert store.build_context(NEW)[0]["value"] == {"safe": True}
    print("PASS: project memory epoch retirement handles skipped epochs without scope leaks")


if __name__ == "__main__": run()
