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
    mutable_value = {"choice": "use adapter", "tags": ["safe"]}
    store.write_project(BASE, key="decision", value=mutable_value, provenance=provenance)

    mutable_value["choice"] = "tampered"
    mutable_value["tags"].append("leak")
    provenance["source"] = "tampered"
    visible = store.read_project(BASE)
    assert len(visible) == 1
    assert visible[0].value == {"choice": "use adapter", "tags": ["safe"]}
    assert visible[0].provenance == {"source": "captain", "kind": "user-confirmed"}

    visible[0].value["tags"].append("consumer-mutation")
    context = store.build_context(BASE)
    context[0]["value"]["tags"].append("context-mutation")
    assert store.build_context(BASE) == (
        {"key": "decision", "value": {"choice": "use adapter", "tags": ["safe"]},
         "provenance": {"source": "captain", "kind": "user-confirmed"}},
    )

    for field, value in (("state_epoch", 5), ("chat_id", "chat-b"),
                         ("project_id", "project-b"), ("repo_scope_hash", H2)):
        current = changed(field, value)
        assert store.read_project(current) == (), field
        assert store.build_context(current) == (), field

    assert store.read_project({**BASE, "state_epoch": 0}) == ()
    assert store.read_project({**BASE, "state_epoch": True}) == ()
    assert store.read_project({**BASE, "repo_scope_hash": "raw/path"}) == ()
    assert store.build_context({"chat_id": "ordinary-chat", "message": "hello"}) == ()

    try:
        store.write_project({"chat_id": "ordinary-chat"}, key="x", value=1, provenance={})
    except MemoryAuthorityError:
        pass
    else:
        raise AssertionError("malformed project-memory write must fail closed")

    for bad in ({}, {"source": "captain"},
                {"source": "captain", "kind": "user-confirmed", "secret": "must-not-persist"},
                {"source": "", "kind": "user-confirmed"}):
        try:
            store.write_project(BASE, key="bad", value=1, provenance=bad)
        except MemoryAuthorityError:
            pass
        else:
            raise AssertionError(f"bad provenance accepted: {bad!r}")

    # Memory values must be inert JSON-shaped data. In particular, do not invoke
    # arbitrary caller-defined __deepcopy__ hooks at the trust boundary.
    class HostileValue:
        called = False
        def __deepcopy__(self, memo):
            type(self).called = True
            raise AssertionError("untrusted copy hook executed")

    for bad_value in (HostileValue(), {"bad": HostileValue()}, {1: "non-string-key"}, {"x": (1, 2)}):
        try:
            store.write_project(BASE, key="unsafe", value=bad_value,
                                provenance={"source": "captain", "kind": "derived"})
        except MemoryAuthorityError:
            pass
        else:
            raise AssertionError(f"unsafe memory value accepted: {bad_value!r}")
    assert HostileValue.called is False

    too_deep = 0
    for _ in range(34):
        too_deep = [too_deep]
    try:
        store.write_project(BASE, key="deep", value=too_deep,
                            provenance={"source": "captain", "kind": "derived"})
    except MemoryAuthorityError:
        pass
    else:
        raise AssertionError("excessively nested memory accepted")

    assert len(tuple(store.all_records_for_test_only())) == 1
    print("PASS: project memory is epoch-bound, inert, provenance-gated and mutation-isolated")


if __name__ == "__main__":
    run()
