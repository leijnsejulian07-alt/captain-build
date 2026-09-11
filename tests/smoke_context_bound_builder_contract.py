"""Regression: OpenBuilder sessions must originate from Captain context."""

from src.captain.builder_lifecycle import BuilderLifecycleCoordinator
from src.captain.context_assembly import ContextAssembler
from src.captain.context_bound_builder import ContextBoundBuilder
from src.captain.memory_context_store import EpochBoundMemoryContextStore, MemoryContextRecord
from src.captain.project_authority import AuthorityError, ProjectAuthority, ScopedRecord
from src.captain.request_context_gateway import RequestContextGateway


def must_fail(fn):
    try:
        fn()
    except AuthorityError:
        return
    raise AssertionError("expected fail-closed AuthorityError")


def put(store, authority, record_id, value):
    store.put(
        MemoryContextRecord(
            record_id=record_id,
            kind="memory",
            payload={"value": value},
            scope=ScopedRecord(authority=authority),
        ),
        actor=authority,
        current_epoch=authority.state_epoch,
    )


def main() -> None:
    store = EpochBoundMemoryContextStore()
    a7 = ProjectAuthority("chat-a", "project-a", "repo-a", 7)
    a8 = ProjectAuthority("chat-a", "project-a", "repo-a", 8)
    b8 = ProjectAuthority("chat-b", "project-b", "repo-b", 8)
    normal = ProjectAuthority()
    put(store, a7, "project", "stale")
    put(store, a8, "project", "current")
    put(store, b8, "project", "other")

    gateway = RequestContextGateway(ContextAssembler(store))
    lifecycle = BuilderLifecycleCoordinator()
    builder = ContextBoundBuilder(gateway=gateway, lifecycle=lifecycle)

    started = builder.open_session(
        "s1",
        request=a8,
        current_epoch=8,
        capabilities=("files.read", "tests.run"),
        payload={"provider": "openbuilder"},
    )
    assert started.session.authority == a8
    assert started.context.authority == a8
    assert started.context.current_epoch == 8
    assert started.context.repo_scope == "repo-a"
    values = {item.payload["value"] for item in started.context.prompt_context.items}
    assert values == {"current"}

    # Stale, normal-chat and cross-project context can never authorize a session.
    must_fail(
        lambda: builder.open_session(
            "stale", request=a7, current_epoch=8, payload={}
        )
    )
    must_fail(
        lambda: builder.open_session(
            "global", request=normal, current_epoch=0, payload={}
        )
    )
    assert lifecycle.resources.get(
        "s1", request=b8, current_epoch=8, resource_type="session"
    ) is None

    # Security boundaries are composition points, not subclass extension points.
    class FakeGateway(RequestContextGateway):
        pass

    must_fail(
        lambda: ContextBoundBuilder(
            gateway=FakeGateway(ContextAssembler(store)), lifecycle=lifecycle
        )
    )

    class FakeLifecycle(BuilderLifecycleCoordinator):
        pass

    must_fail(
        lambda: ContextBoundBuilder(
            gateway=gateway, lifecycle=FakeLifecycle()
        )
    )

    print("PASS: builder session creation is bound to canonical Captain context")


if __name__ == "__main__":
    main()
