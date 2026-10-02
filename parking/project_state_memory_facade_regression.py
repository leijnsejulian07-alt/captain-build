"""Integration regressions for Captain Project-State-owned memory facade.

Parking acceptance test: proves an epoch advance retires stale project memory/context,
keeps other project/repo scopes isolated, and leaves ordinary non-project chat outside
project-memory authority rather than coercing it into a project.
"""
from memory_authority import MemoryAuthorityError
from project_state_memory_facade import ProjectStateMemoryFacade

H1 = "a" * 64
H2 = "b" * 64
E7 = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope_hash": H1, "state_epoch": 7}
E8 = {**E7, "state_epoch": 8}
OTHER = {"chat_id": "chat-b", "project_id": "project-b", "repo_scope_hash": H2, "state_epoch": 3}
PROV = {"source": "regression", "kind": "user_fact"}


def run():
    memory = ProjectStateMemoryFacade()
    memory.write_current(E7, key="secret", value={"v": "epoch-7"}, provenance=PROV)
    memory.write_current(OTHER, key="other", value={"v": "other-project"}, provenance=PROV)

    assert [r.key for r in memory.read_current(E7)] == ["secret"]
    assert [r["key"] for r in memory.build_current_context(E7)] == ["secret"]
    assert [r.key for r in memory.read_current(OTHER)] == ["other"]

    removed = memory.advance(E7, E8)
    assert removed == 1

    # Stale authority cannot read or rebuild context after the Project State epoch moves.
    assert memory.read_current(E7) == ()
    assert memory.build_current_context(E7) == ()
    assert memory.read_current(E8) == ()
    assert memory.build_current_context(E8) == ()

    # A different exact project/repo authority survives an unrelated epoch transition.
    assert [r.key for r in memory.read_current(OTHER)] == ["other"]

    # Normal non-project chat remains useful by staying outside project memory.
    normal_chat = {"chat_id": "ordinary-chat", "message": "hello"}
    assert memory.read_current(normal_chat) == ()
    assert memory.build_current_context(normal_chat) == ()

    # No caller may smuggle extra authority fields or a boolean epoch.
    assert memory.read_current({**E8, "repo_scope": "raw/path"}) == ()
    assert memory.read_current({**E8, "state_epoch": True}) == ()

    # Writes fail closed rather than silently creating project memory from normal chat.
    try:
        memory.write_current(normal_chat, key="x", value=1, provenance=PROV)
    except (MemoryAuthorityError, TypeError):
        pass
    else:
        raise AssertionError("non-project chat was allowed to create project memory")

    print("PASS: Project State memory/context is epoch-bound and normal chat stays separate")


if __name__ == "__main__":
    run()
