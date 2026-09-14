from __future__ import annotations

from parking.integration.builder_output_handles import BuilderOutputHandleStore
from parking.integration.project_epoch_transition import apply_project_epoch_transition
from parking.integration.project_memory_context_store import MemoryContextStoreError, ProjectMemoryContextStore


def expect(exc_type, fn) -> None:
    try:
        fn()
        raise AssertionError(f"expected {exc_type.__name__}")
    except exc_type:
        pass


def main() -> None:
    scope = dict(chat_id="chat-a", project_id="proj-a", repo_scope="acme/repo-a")
    other_project = dict(chat_id="chat-a", project_id="proj-b", repo_scope="acme/repo-b")
    store = ProjectMemoryContextStore()

    stale_memory = store.register(kind="project_memory", state_epoch=1, record_id="memory-old", **scope)
    current_memory = store.register(kind="project_memory", state_epoch=2, record_id="memory-new", **scope)
    stale_context = store.register(kind="project_context", state_epoch=1, record_id="context-old", **scope)
    other = store.register(kind="project_memory", state_epoch=1, record_id="other-memory", **other_project)

    assert stale_memory.state_epoch == 1
    assert current_memory.state_epoch == 2
    assert stale_context.kind == "project_context"
    assert other.record_id == "other-memory"

    expect(PermissionError, lambda: store.authorize("memory-old", current_epoch=2, **scope))
    assert store.authorize("memory-new", current_epoch=2, **scope).record_id == "memory-new"
    expect(PermissionError, lambda: store.authorize("memory-new", current_epoch=2, **other_project))

    # Idempotent duplicate registration is safe; authority-changing reuse is not.
    assert store.register(kind="project_memory", state_epoch=2, record_id="memory-new", **scope) == current_memory
    expect(MemoryContextStoreError, lambda: store.register(
        kind="project_context", state_epoch=2, record_id="memory-new", **scope
    ))

    builder_outputs = BuilderOutputHandleStore(b"m" * 32)
    result = apply_project_epoch_transition(
        previous_epoch=1,
        current_epoch=2,
        builder_outputs=builder_outputs,
        additional_cleanups={"memory_context": store},
        **scope,
    )
    assert result.cleanup_counts == (("builder_outputs", 0), ("memory_context", 2))
    assert store.count_for_scope(scope) == 1
    assert store.count_for_scope(other_project) == 1
    expect(PermissionError, lambda: store.authorize("memory-old", current_epoch=2, **scope))
    expect(PermissionError, lambda: store.authorize("context-old", current_epoch=2, **scope))
    assert store.authorize("memory-new", current_epoch=2, **scope).record_id == "memory-new"
    assert store.authorize("other-memory", current_epoch=1, **other_project).record_id == "other-memory"

    # Repeating cleanup is harmless and exact-scope only.
    assert store.revoke_stale_epochs(current_epoch=2, **scope) == 0
    assert store.count_for_scope(scope) == 1
    assert store.count_for_scope(other_project) == 1

    for bad_epoch in (0, -1, True, "2"):
        expect(ValueError, lambda bad_epoch=bad_epoch: store.revoke_stale_epochs(current_epoch=bad_epoch, **scope))


if __name__ == "__main__":
    main()
