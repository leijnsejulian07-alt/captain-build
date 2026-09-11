from src.captain.context_assembly import ContextAssembler, PromptContextBundle
from src.captain.memory_context_store import EpochBoundMemoryContextStore, MemoryContextRecord
from src.captain.project_authority import AuthorityError, ProjectAuthority, ScopedRecord
from src.captain.request_context_gateway import RequestContextGateway


def project(name: str, epoch: int) -> ProjectAuthority:
    return ProjectAuthority(
        chat_id=f"chat-{name}",
        project_id=f"project-{name}",
        repo_scope=f"repo-{name}",
        state_epoch=epoch,
    )


def put(store, actor, record_id, value, *, generic=False, project_specific=True):
    store.put(
        MemoryContextRecord(
            record_id=record_id,
            kind="memory",
            payload={"value": value},
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
    b8 = project("b", 8)

    put(store, normal, "generic", "shared", generic=True, project_specific=False)
    put(store, normal, "chat-only", "normal")
    put(store, a7, "project", "stale")
    put(store, a8, "project", "current")
    put(store, b8, "project", "other-project")

    gateway = RequestContextGateway(ContextAssembler(store))

    model = gateway.for_model(request=a8, current_epoch=8)
    assert model.authority == a8
    assert model.current_epoch == 8
    model_values = {item.record_id: item.payload["value"] for item in model.prompt_context.items}
    assert model_values == {"project": "current", "generic": "shared"}
    assert "other-project" not in model_values.values()
    assert "stale" not in model_values.values()

    normal_model = gateway.for_model(request=normal)
    normal_values = {item.record_id: item.payload["value"] for item in normal_model.prompt_context.items}
    assert normal_values == {"generic": "shared", "chat-only": "normal"}

    expect_denied(lambda: gateway.for_model(request=a7, current_epoch=8))
    expect_denied(lambda: gateway.for_model(request=a8))
    expect_denied(lambda: gateway.for_model(request=normal, current_epoch=0))

    builder = gateway.for_builder(
        request=a8,
        current_epoch=8,
        capabilities=("files.read", "repo.diff", "tests.run"),
    )
    assert builder.authority == a8
    assert builder.current_epoch == 8
    assert builder.repo_scope == "repo-a"
    assert builder.capabilities == ("files.read", "repo.diff", "tests.run")
    assert builder.prompt_context == model.prompt_context

    # OpenBuilder must never become a global/normal-chat memory consumer.
    expect_denied(lambda: gateway.for_builder(request=normal, current_epoch=0))
    expect_denied(lambda: gateway.for_builder(request=a7, current_epoch=8))

    # Capability grants are explicit immutable metadata, not arbitrary caller data.
    expect_denied(
        lambda: gateway.for_builder(
            request=a8, current_epoch=8, capabilities=["files.read"]
        )
    )
    expect_denied(
        lambda: gateway.for_builder(
            request=a8, current_epoch=8, capabilities=("files.read", "files.read")
        )
    )
    expect_denied(
        lambda: gateway.for_builder(
            request=a8, current_epoch=8, capabilities=(" files.read",)
        )
    )

    # Even a ContextAssembler subclass cannot trick the gateway into returning
    # a bundle for another project or epoch.
    class CompromisedAssembler(ContextAssembler):
        def assemble(self, **_kwargs):
            return PromptContextBundle(authority=b8, current_epoch=8, items=())

    compromised = RequestContextGateway(CompromisedAssembler(store))
    expect_denied(lambda: compromised.for_model(request=a8, current_epoch=8))
    expect_denied(
        lambda: compromised.for_builder(request=a8, current_epoch=8)
    )

    print(
        "PASS: model and OpenBuilder context share one Captain-owned epoch-bound gateway"
    )


if __name__ == "__main__":
    main()
