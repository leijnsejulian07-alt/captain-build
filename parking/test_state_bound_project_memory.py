"""Regression for Captain-owned live Project State memory boundary."""
import inspect

from memory_authority import MemoryAuthorityError
from state_bound_project_memory import StateBoundProjectMemory

H = "a" * 64
H2 = "b" * 64
E4 = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope_hash": H, "state_epoch": 4}
E5 = {**E4, "state_epoch": 5}
OTHER_PROJECT = {**E4, "project_id": "project-b"}
OTHER_CHAT = {**E4, "chat_id": "chat-b"}
OTHER_REPO = {**E4, "repo_scope_hash": H2}
PROV = {"source": "captain", "kind": "derived"}


def run():
    state = {"current": E4}
    memory = StateBoundProjectMemory(lambda: state["current"])

    # Runtime/plugin surface must not expose an all-scope persistence export.\n    assert not hasattr(memory, "snapshot_for_persistence")\n\n    # Runtime surface cannot accept caller-supplied authority/current.
    for name in ("write", "read", "build_context"):
        params = inspect.signature(getattr(memory, name)).parameters
        assert "current" not in params and "authority" not in params

    memory.write(key="decision", value={"v": 4}, provenance=PROV)
    assert memory.build_context()[0]["value"] == {"v": 4}

    # Epoch advance is discovered live and retires stale same-scope memory.
    state["current"] = E5
    assert memory.build_context() == ()
    memory.write(key="decision", value={"v": 5}, provenance=PROV)
    assert memory.build_context()[0]["value"] == {"v": 5}

    # Every authority-wall dimension is isolated independently.
    for foreign in (OTHER_PROJECT, OTHER_CHAT, OTHER_REPO):
        state["current"] = foreign
        assert memory.read() == ()
        assert memory.build_context() == ()

    # Returning to the current live scope restores only that scope's epoch-5 memory.
    state["current"] = E5
    assert memory.build_context()[0]["value"] == {"v": 5}

    # Returning to an older epoch for the original scope fails closed.
    state["current"] = E4
    assert memory.read() == ()
    assert memory.build_context() == ()
    try:
        memory.write(key="stale", value=1, provenance=PROV)
    except MemoryAuthorityError:
        pass
    else:
        raise AssertionError("stale epoch write was accepted")

    # Ordinary/non-project chat remains usable outside this project-memory adapter:
    # this adapter simply contributes no project context when no valid Project State exists.
    state["current"] = {"chat_id": "ordinary-chat"}
    assert memory.read() == ()
    assert memory.build_context() == ()

    print("PASS: live resolver owns memory authority; stale/cross-project/cross-chat/cross-repo context is inaccessible")


if __name__ == "__main__":
    run()
