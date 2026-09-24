"""Regression for the Project-State-owned memory facade."""
from memory_authority import MemoryAuthorityError
from project_state_memory_facade import ProjectStateMemoryFacade

H = "a" * 64
E4 = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope_hash": H, "state_epoch": 4}
E5 = {**E4, "state_epoch": 5}
OTHER = {**E4, "project_id": "project-b"}
PROV = {"source": "captain", "kind": "derived"}


def run():
    memory = ProjectStateMemoryFacade()
    memory.write_current(E4, key="decision", value={"v": 4}, provenance=PROV)
    assert memory.build_current_context(E4)[0]["value"] == {"v": 4}
    assert memory.build_current_context(E5) == ()
    assert memory.build_current_context(OTHER) == ()

    # Project State, not a plugin/builder payload, stamps the authority. The public
    # write surface intentionally has no claimed-authority or epoch override field.
    try:
        memory.write_current(E4, key="bad", value=1, provenance=PROV,
                             authority=E5)  # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError("caller could override Captain Project State authority")
    assert memory.build_current_context(E4)[0]["key"] == "decision"
    assert memory.build_current_context(E5) == ()

    removed = memory.advance(E4, E5)
    assert removed == 1
    assert memory.build_current_context(E4) == ()
    assert memory.build_current_context(E5) == ()
    memory.write_current(E5, key="decision", value={"v": 5}, provenance=PROV)
    assert memory.build_current_context(E5)[0]["value"] == {"v": 5}

    # Malformed/non-project state remains unusable without affecting valid memory.
    for bad in ({"chat_id": "ordinary-chat"}, {**E5, "state_epoch": True},
                {**E5, "repo_scope_hash": "raw/path"}):
        assert memory.read_current(bad) == ()
        assert memory.build_current_context(bad) == ()
        try:
            memory.write_current(bad, key="x", value=1, provenance=PROV)
        except (MemoryAuthorityError, TypeError):
            pass
        else:
            raise AssertionError("malformed Project State accepted for memory write")
    assert memory.build_current_context(E5)[0]["value"] == {"v": 5}
    print("PASS: Project State stamps memory writes and stale/cross-project context stays isolated")


if __name__ == "__main__": run()
