"""Regression: OpenBuilder phases cannot skip Captain-owned causal gates."""

from src.captain.builder_action_receipts import BuilderActionReceipt
from src.captain.builder_lifecycle import BuilderLifecycleCoordinator
from src.captain.builder_resource_store import BuilderResource
from src.captain.project_authority import AuthorityError, ProjectAuthority


def must_fail(fn):
    try:
        fn()
    except AuthorityError:
        return
    raise AssertionError("expected fail-closed AuthorityError")


def receipt(authority, action_id, phase, status="succeeded"):
    return BuilderActionReceipt(action_id, "s1", phase, status, authority, {})


def record(lifecycle, authority, action_id, phase, status="succeeded"):
    item = receipt(authority, action_id, phase, status)
    lifecycle.record_action(item, actor=authority, current_epoch=authority.state_epoch)
    return item


def main() -> None:
    authority = ProjectAuthority("chat", "project", "repo", 4)
    lifecycle = BuilderLifecycleCoordinator()
    lifecycle.open_session("s1", actor=authority, current_epoch=4, payload={})

    # The happy path is strictly causal.
    must_fail(lambda: record(lifecycle, authority, "build-early", "build", "queued"))
    record(lifecycle, authority, "plan", "plan")
    record(lifecycle, authority, "build", "build")
    lifecycle.put_resource(
        BuilderResource("diff", "d1", authority, {"files": 2}),
        session_id="s1",
        actor=authority,
        current_epoch=4,
    )
    must_fail(lambda: record(lifecycle, authority, "review-early", "review", "queued"))

    # A test failure permits debug; successful debug invalidates test/review/preview.
    record(lifecycle, authority, "test-fail", "test", "failed")
    must_fail(lambda: record(lifecycle, authority, "preview-early", "preview", "queued"))
    record(lifecycle, authority, "debug", "debug")
    must_fail(lambda: record(lifecycle, authority, "review-after-debug", "review", "queued"))
    record(lifecycle, authority, "test-2", "test")
    record(lifecycle, authority, "review", "review")
    record(lifecycle, authority, "preview", "preview")
    lifecycle.put_resource(
        BuilderResource("preview", "p1", authority, {"url": "http://local"}),
        session_id="s1",
        actor=authority,
        current_epoch=4,
    )

    # Rollback is allowed only after a real build and invalidates that live candidate.
    record(lifecycle, authority, "rollback", "rollback")
    lifecycle.put_resource(
        BuilderResource("rollback", "r1", authority, {"checkpoint": "before-build"}),
        session_id="s1",
        actor=authority,
        current_epoch=4,
    )
    must_fail(lambda: record(lifecycle, authority, "test-after-rollback", "test", "queued"))

    # Duplicate session open fails before it can replace the original session payload.
    must_fail(lambda: lifecycle.open_session("s1", actor=authority, current_epoch=4, payload={"x": 2}))
    stored = lifecycle.resources.get(
        "s1", request=authority, current_epoch=4, resource_type="session"
    )
    assert stored is not None
    assert dict(stored.payload) == {}

    print("PASS: Captain enforces causal builder phase/resource ordering")


if __name__ == "__main__":
    main()
