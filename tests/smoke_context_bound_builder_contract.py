"""Regression: all OpenBuilder work must originate from Captain context."""

from src.captain.builder_action_receipts import BuilderActionReceipt
from src.captain.builder_lifecycle import BuilderLifecycleCoordinator
from src.captain.builder_resource_store import BuilderResource
from src.captain.builder_update_stream import BuilderUpdate
from src.captain.context_assembly import ContextAssembler
from src.captain.context_bound_builder import BuilderSessionStart, ContextBoundBuilder
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


def record(builder, started, authority, action_id, phase, status="succeeded"):
    receipt = BuilderActionReceipt(action_id, "s1", phase, status, authority, {})
    builder.record_action(started, receipt, current_epoch=authority.state_epoch)
    return receipt


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
    values = {item.payload["value"] for item in started.context.prompt_context.items}
    assert values == {"current"}

    # Ownership and causal ordering are both Captain-owned.
    premature = BuilderActionReceipt("too-soon", "s1", "build", "queued", a8, {})
    must_fail(lambda: builder.record_action(started, premature, current_epoch=8))
    must_fail(
        lambda: builder.put_resource(
            started,
            BuilderResource("preview", "early", a8, {"url": "http://invalid"}),
            current_epoch=8,
        )
    )

    record(builder, started, a8, "plan-1", "plan")
    action = record(builder, started, a8, "build-1", "build")
    record(builder, started, a8, "test-1", "test")
    record(builder, started, a8, "review-1", "review")
    record(builder, started, a8, "preview-1", "preview")

    update = BuilderUpdate("u1", "s1", "status", 1, a8, {"message": "building"})
    assert builder.publish_update(started, update, current_epoch=8)
    preview = BuilderResource("preview", "p1", a8, {"url": "http://local.test"})
    builder.put_resource(started, preview, current_epoch=8)
    assert lifecycle.resources.get(
        "p1", request=a8, current_epoch=8, resource_type="preview"
    ) is not None

    # A structurally identical token fabricated by an adapter is not authority.
    forged = BuilderSessionStart(context=started.context, session=started.session)
    must_fail(lambda: builder.record_action(forged, action, current_epoch=8))
    must_fail(lambda: builder.publish_update(forged, update, current_epoch=8))
    must_fail(lambda: builder.put_resource(forged, preview, current_epoch=8))

    # Session mixups and stale epochs fail closed even with a valid token.
    wrong_session = BuilderActionReceipt("a2", "other", "test", "queued", a8, {})
    must_fail(lambda: builder.record_action(started, wrong_session, current_epoch=8))
    must_fail(lambda: builder.record_action(started, action, current_epoch=9))

    # The bridge no longer exposes its raw lifecycle as an adapter escape hatch.
    assert not hasattr(builder, "lifecycle")

    # Stale, normal-chat and cross-project context can never authorize a session.
    must_fail(lambda: builder.open_session("stale", request=a7, current_epoch=8, payload={}))
    must_fail(lambda: builder.open_session("global", request=normal, current_epoch=0, payload={}))
    assert lifecycle.resources.get(
        "s1", request=b8, current_epoch=8, resource_type="session"
    ) is None

    class FakeGateway(RequestContextGateway):
        pass

    must_fail(
        lambda: ContextBoundBuilder(
            gateway=FakeGateway(ContextAssembler(store)), lifecycle=lifecycle
        )
    )

    class FakeLifecycle(BuilderLifecycleCoordinator):
        pass

    must_fail(lambda: ContextBoundBuilder(gateway=gateway, lifecycle=FakeLifecycle()))

    print("PASS: builder lifecycle is context-bound and phase-gated by Captain")


if __name__ == "__main__":
    main()
