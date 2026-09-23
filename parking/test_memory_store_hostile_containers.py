"""Regression: memory boundary must not execute container/provenance hooks."""
from memory_authority import MemoryAuthorityError
from memory_store_epoch_adapter import EpochBoundMemoryStore

H = "a" * 64
AUTH = {"chat_id": "chat", "project_id": "project", "repo_scope_hash": H, "state_epoch": 1}

class HostileDict(dict):
    called = False
    def items(self):
        type(self).called = True
        raise AssertionError("hostile dict.items executed")

class HostileList(list):
    called = False
    def __iter__(self):
        type(self).called = True
        raise AssertionError("hostile list iterator executed")

class HostileProvenance(dict):
    called = False
    def __iter__(self):
        type(self).called = True
        raise AssertionError("hostile provenance iterator executed")


def reject(store, *, value=1, provenance=None):
    if provenance is None:
        provenance = {"source": "captain", "kind": "derived"}
    try:
        store.write_project(AUTH, key="x", value=value, provenance=provenance)
    except MemoryAuthorityError:
        return
    raise AssertionError("hostile container accepted")


def run():
    store = EpochBoundMemoryStore()
    reject(store, value=HostileDict({"x": 1}))
    reject(store, value=HostileList([1]))
    reject(store, provenance=HostileProvenance(source="captain", kind="derived"))
    assert not HostileDict.called
    assert not HostileList.called
    assert not HostileProvenance.called
    print("PASS: executable container/provenance subclasses fail closed without hooks")

if __name__ == "__main__":
    run()
