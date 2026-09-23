"""Regression: many individually-valid strings cannot bypass the total text budget."""
from memory_authority import MemoryAuthorityError
from memory_store_epoch_adapter import (
    EpochBoundMemoryStore,
    MAX_STRING_CHARS,
    MAX_TOTAL_TEXT_CHARS,
)

H = "a" * 64
AUTH = {"chat_id": "chat", "project_id": "project", "repo_scope_hash": H, "state_epoch": 1}
PROV = {"source": "captain", "kind": "derived"}


def run():
    store = EpochBoundMemoryStore()

    # Every string is legal by itself, but their aggregate must fail closed.
    chunk = "x" * min(MAX_STRING_CHARS, MAX_TOTAL_TEXT_CHARS // 2 + 1)
    try:
        store.write_project(AUTH, key="too-wide", value=[chunk, chunk], provenance=PROV)
    except MemoryAuthorityError as exc:
        assert "aggregate text budget" in str(exc)
    else:
        raise AssertionError("aggregate text budget bypassed")

    assert tuple(store.all_records_for_test_only()) == ()

    # A normal payload remains usable after the rejected oversized write.
    store.write_project(AUTH, key="ok", value={"summary": "small"}, provenance=PROV)
    context = store.build_context(AUTH)
    assert len(context) == 1
    assert context[0]["key"] == "ok"
    assert context[0]["value"] == {"summary": "small"}
    print("PASS: aggregate memory text budget fails closed without poisoning later writes")


if __name__ == "__main__":
    run()
