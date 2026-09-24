"""Regression: persistence cannot bypass Captain's Project State memory facade."""
from memory_authority import MemoryAuthorityError
from project_state_memory_facade import ProjectStateMemoryFacade

H = "a" * 64
E4 = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope_hash": H, "state_epoch": 4}
E5 = {**E4, "state_epoch": 5}
OTHER = {**E4, "project_id": "project-b"}
PROV = {"source": "captain", "kind": "derived"}


def run():
    memory = ProjectStateMemoryFacade()
    memory.write_current(E4, key="decision", value={"nested": [1, 2]}, provenance=PROV)

    # Persistence receives detached inert data, never the mutable backing store.
    persisted = memory.snapshot_for_persistence()
    persisted["records"][0]["value"]["nested"].append(999)
    persisted["records"][0]["authority"]["state_epoch"] = 99
    assert memory.build_current_context(E4)[0]["value"] == {"nested": [1, 2]}
    assert memory.build_current_context({**E4, "state_epoch": 99}) == ()

    # A clean snapshot round-trips while preserving exact authority isolation.
    clean = memory.snapshot_for_persistence()
    restored = ProjectStateMemoryFacade.from_persisted_snapshot(clean)
    assert restored.build_current_context(E4)[0]["value"] == {"nested": [1, 2]}
    assert restored.build_current_context(E5) == ()
    assert restored.build_current_context(OTHER) == ()

    # Tampered persisted authority cannot be silently accepted as current state.
    tampered = memory.snapshot_for_persistence()
    tampered["records"][0]["authority"]["state_epoch"] = True
    try:
        ProjectStateMemoryFacade.from_persisted_snapshot(tampered)
    except MemoryAuthorityError:
        pass
    else:
        raise AssertionError("tampered persisted authority restored")

    # The former raw-store escape hatch must stay absent.
    assert not hasattr(memory, "snapshot_store_for_persistence")
    assert not hasattr(memory, "store")
    print("PASS: Project State memory persistence is detached, validated and store-sealed")


if __name__ == "__main__": run()
