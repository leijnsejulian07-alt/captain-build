"""Regressions for the epoch-bound project memory/context adapter."""
from memory_authority import MemoryAuthorityError
from memory_store_epoch_adapter import (
    EpochBoundMemoryStore, MAX_JSON_NODES, MAX_KEY_CHARS, MAX_PROVENANCE_CHARS,
    MAX_RECORDS_PER_AUTHORITY,
)

H1 = "1" * 64
H2 = "2" * 64
BASE = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope_hash": H1, "state_epoch": 4}


def changed(field, value):
    result = dict(BASE); result[field] = value; return result


def must_reject(store, value):
    try:
        store.write_project(BASE, key="unsafe", value=value,
                            provenance={"source": "captain", "kind": "derived"})
    except MemoryAuthorityError: return
    raise AssertionError(f"unsafe memory value accepted: {type(value).__name__}")


def must_reject_write(store, *, key="x", provenance=None):
    provenance = provenance or {"source": "captain", "kind": "derived"}
    try: store.write_project(BASE, key=key, value=1, provenance=provenance)
    except MemoryAuthorityError: return
    raise AssertionError("unsafe memory metadata accepted")


def run():
    store = EpochBoundMemoryStore()
    provenance = {"source": "captain", "kind": "user-confirmed"}
    mutable_value = {"choice": "use adapter", "tags": ["safe"]}
    store.write_project(BASE, key="decision", value=mutable_value, provenance=provenance)
    mutable_value["choice"] = "tampered"; mutable_value["tags"].append("leak")
    provenance["source"] = "tampered"
    visible = store.read_project(BASE)
    assert len(visible) == 1
    assert visible[0].value == {"choice": "use adapter", "tags": ["safe"]}
    assert visible[0].provenance == {"source": "captain", "kind": "user-confirmed"}
    visible[0].value["tags"].append("consumer-mutation")
    context = store.build_context(BASE); context[0]["value"]["tags"].append("context-mutation")
    assert store.build_context(BASE)[0]["value"]["tags"] == ["safe"]

    # Same authority + key is a replacement, not context inflation.
    store.write_project(BASE, key="decision", value={"choice": "updated"},
                        provenance={"source": "captain", "kind": "derived"})
    assert len(store.read_project(BASE)) == 1
    assert store.read_project(BASE)[0].value == {"choice": "updated"}

    for field, value in (("state_epoch", 5), ("chat_id", "chat-b"),
                         ("project_id", "project-b"), ("repo_scope_hash", H2)):
        assert store.read_project(changed(field, value)) == (), field
        assert store.build_context(changed(field, value)) == (), field
    assert store.read_project({**BASE, "state_epoch": 0}) == ()
    assert store.read_project({**BASE, "state_epoch": True}) == ()
    assert store.read_project({**BASE, "repo_scope_hash": "raw/path"}) == ()
    assert store.build_context({"chat_id": "ordinary-chat", "message": "hello"}) == ()
    must_reject_write(store, key=" " * 3)
    must_reject_write(store, key="k" * (MAX_KEY_CHARS + 1))
    must_reject_write(store, provenance={"source": "s" * (MAX_PROVENANCE_CHARS + 1), "kind": "derived"})
    must_reject_write(store, provenance={"source": "captain", "kind": "k" * (MAX_PROVENANCE_CHARS + 1)})
    for bad in ({}, {"source": "captain"},
                {"source": "captain", "kind": "user-confirmed", "secret": "must-not-persist"},
                {"source": "", "kind": "user-confirmed"}):
        must_reject_write(store, provenance=bad)

    class HostileValue:
        called = False
        def __deepcopy__(self, memo):
            type(self).called = True; raise AssertionError("untrusted copy hook executed")
    for bad_value in (HostileValue(), {"bad": HostileValue()}, {1: "non-string-key"},
                      {"x": (1, 2)}, float("nan"), float("inf"), float("-inf")):
        must_reject(store, bad_value)
    assert HostileValue.called is False
    too_deep = 0
    for _ in range(34): too_deep = [too_deep]
    must_reject(store, too_deep)
    must_reject(store, [0] * (MAX_JSON_NODES + 1))

    # Fill an isolated authority to its exact budget. It must neither evict nor
    # borrow capacity from BASE; an existing key remains replaceable when full.
    full_auth = changed("project_id", "project-full")
    for i in range(MAX_RECORDS_PER_AUTHORITY):
        store.write_project(full_auth, key=f"k{i}", value=i,
                            provenance={"source": "captain", "kind": "derived"})
    assert len(store.read_project(full_auth)) == MAX_RECORDS_PER_AUTHORITY
    try:
        store.write_project(full_auth, key="overflow", value=1,
                            provenance={"source": "captain", "kind": "derived"})
    except MemoryAuthorityError:
        pass
    else:
        raise AssertionError("full authority accepted a new memory key")
    store.write_project(full_auth, key="k0", value="replacement",
                        provenance={"source": "captain", "kind": "derived"})
    assert len(store.read_project(full_auth)) == MAX_RECORDS_PER_AUTHORITY
    assert store.read_project(full_auth)[0].value == "replacement"
    assert len(store.read_project(BASE)) == 1
    print("PASS: project memory authority, payload, metadata and cardinality boundaries fail closed")


if __name__ == "__main__": run()
