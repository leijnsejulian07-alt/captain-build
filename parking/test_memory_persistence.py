"""Regress versioned persistence without weakening Captain memory authority walls."""
from memory_authority import MemoryAuthorityError
from memory_persistence import restore, snapshot
from memory_store_epoch_adapter import EpochBoundMemoryStore

H1 = "1" * 64
BASE = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope_hash": H1, "state_epoch": 4}


def rejected(data):
    try:
        restore(data)
    except (MemoryAuthorityError, TypeError):
        return
    raise AssertionError("unsafe persisted memory accepted")


def run():
    store = EpochBoundMemoryStore()
    store.write_project(BASE, key="decision", value={"choice": "safe", "tags": ["x"]},
                        provenance={"source": "captain", "kind": "user-confirmed"})
    persisted = snapshot(store)
    persisted["records"][0]["value"]["tags"].append("snapshot-mutation")
    assert store.build_context(BASE)[0]["value"]["tags"] == ["x"]

    persisted = snapshot(store)
    restored = restore(persisted)
    assert restored.build_context(BASE) == store.build_context(BASE)
    assert restored.build_context({**BASE, "state_epoch": 5}) == ()
    persisted["records"][0]["value"]["tags"].append("post-restore-mutation")
    assert restored.build_context(BASE)[0]["value"]["tags"] == ["x"]

    rejected({"version": 2, "records": []})
    rejected({"version": 1, "records": {}, "extra": 1})
    rejected({"version": 1, "records": [{"authority": BASE, "key": "x",
              "value": float("nan"), "provenance": {"source": "captain", "kind": "derived"}}]})
    duplicate = snapshot(store)
    duplicate["records"].append(dict(duplicate["records"][0]))
    rejected(duplicate)

    class HostileList(list):
        called = False
        def __iter__(self):
            type(self).called = True
            raise AssertionError("hostile persisted list executed")
    rejected({"version": 1, "records": HostileList()})
    assert HostileList.called is False
    print("PASS: memory persistence is versioned, detached, epoch-bound and fail closed")


if __name__ == "__main__": run()
