from src.captain.context_assembly import ContextAssembler
from src.captain.memory_context_store import EpochBoundMemoryContextStore, MemoryContextRecord
from src.captain.project_authority import AuthorityError, ProjectAuthority, ScopedRecord


def project(name: str, epoch: int) -> ProjectAuthority:
    return ProjectAuthority(
        chat_id=f"chat-{name}",
        project_id=f"project-{name}",
        repo_scope=f"repo-{name}",
        state_epoch=epoch,
    )


def put(store, actor, record_id, payload, *, generic=False, project_specific=True):
    store.put(
        MemoryContextRecord(
            record_id=record_id,
            kind="memory",
            payload=payload,
            scope=ScopedRecord(
                authority=actor,
                generic=generic,
                project_specific=project_specific,
            ),
        ),
        actor=actor,
        current_epoch=None if actor.is_normal_chat else actor.state_epoch,
    )


def expect_denied(fn):
    try:
        fn()
    except AuthorityError:
        return
    raise AssertionError("expected fail-closed AuthorityError")


def main():
    store = EpochBoundMemoryContextStore()
    normal = ProjectAuthority()
    a7 = project("a", 7)
    a8 = project("a", 8)
    b7 = project("b", 7)

    put(store, a7, "same", {"value": "a7"})
    put(store, a8, "same", {"value": "a8"})
    put(store, b7, "same", {"value": "b7"})
    put(store, normal, "shared", {"value": "generic"}, generic=True, project_specific=False)
    put(store, normal, "chat-only", {"value": "normal"})

    assembler = ContextAssembler(store)
    a8_bundle = assembler.assemble(request=a8, current_epoch=8)
    values = {item.record_id: item.payload["value"] for item in a8_bundle.items}
    assert values == {"same": "a8", "shared": "generic"}
    provenance = {item.record_id: item.provenance for item in a8_bundle.items}
    assert provenance == {"same": "current_project_epoch", "shared": "generic_global"}

    expect_denied(lambda: assembler.assemble(request=a7, current_epoch=8))
    expect_denied(lambda: assembler.assemble(request=a8))

    normal_bundle = assembler.assemble(request=normal)
    normal_ids = {item.record_id for item in normal_bundle.items}
    assert normal_ids == {"shared", "chat-only"}
    assert all(item.provenance == "normal_chat" for item in normal_bundle.items)

    class MaliciousBackend:
        def list_readable(self, **_kwargs):
            return [
                MemoryContextRecord(
                    record_id="leak",
                    kind="memory",
                    payload={"value": "project-b-secret"},
                    scope=ScopedRecord(authority=b7),
                )
            ]

    expect_denied(
        lambda: ContextAssembler(MaliciousBackend()).assemble(request=a7, current_epoch=7)
    )

    class MutableBackend:
        def list_readable(self, **_kwargs):
            return [
                MemoryContextRecord(
                    record_id="mutable",
                    kind="memory",
                    payload={"nested": ["not-frozen"]},
                    scope=ScopedRecord(authority=a8),
                )
            ]

    expect_denied(
        lambda: ContextAssembler(MutableBackend()).assemble(request=a8, current_epoch=8)
    )

    # A backend may legitimately return a plain dict. Captain must take its own
    # immutable snapshot so provider/plugin code cannot mutate model context
    # after authorization and budget checks have completed.
    backend_payload = {"value": "before", "nested": {"flag": True}}

    class FlatMutableBackend:
        def list_readable(self, **_kwargs):
            return [
                MemoryContextRecord(
                    record_id="snapshot",
                    kind="memory",
                    payload=backend_payload,
                    scope=ScopedRecord(authority=a8),
                )
            ]

    snapshot_bundle = ContextAssembler(FlatMutableBackend()).assemble(
        request=a8, current_epoch=8
    )
    snapshot = snapshot_bundle.items[0].payload
    backend_payload["value"] = "after"
    backend_payload["nested"]["flag"] = False
    assert snapshot["value"] == "before"
    assert snapshot["nested"]["flag"] is True
    try:
        snapshot["value"] = "tampered"
    except TypeError:
        pass
    else:
        raise AssertionError("model-facing payload must be immutable")
    try:
        snapshot["nested"]["flag"] = False
    except TypeError:
        pass
    else:
        raise AssertionError("nested model-facing payload must be immutable")

    tiny = ContextAssembler(store, max_records=1)
    expect_denied(lambda: tiny.assemble(request=a8, current_epoch=8))

    print("PASS: prompt context assembly is epoch-bound, immutable, scope-checked, and fail-closed")


if __name__ == "__main__":
    main()
