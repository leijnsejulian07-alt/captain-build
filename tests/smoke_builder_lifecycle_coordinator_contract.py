"""Regression coverage for Captain-owned OpenBuilder lifecycle composition."""

from src.captain.builder_action_receipts import BuilderActionReceipt
from src.captain.builder_lifecycle import BuilderLifecycleCoordinator
from src.captain.builder_resource_store import BuilderResource
from src.captain.builder_update_stream import BuilderUpdate
from src.captain.project_authority import AuthorityError, ProjectAuthority


def must_fail(callable_):
    try:
        callable_()
    except AuthorityError:
        return
    raise AssertionError("expected fail-closed AuthorityError")


def main() -> None:
    a7 = ProjectAuthority("chat-a", "project-a", "repo-a", 7)
    a8 = ProjectAuthority("chat-a", "project-a", "repo-a", 8)
    b8 = ProjectAuthority("chat-b", "project-b", "repo-b", 8)
    normal = ProjectAuthority()
    lifecycle = BuilderLifecycleCoordinator()

    lifecycle.open_session("old", actor=a7, current_epoch=7, payload={"provider": "x"})
    lifecycle.open_session("s1", actor=a8, current_epoch=8, payload={"provider": "x"})

    valid = BuilderActionReceipt("a1", "s1", "build", "running", a8, {"step": 1})
    lifecycle.record_action(valid, actor=a8, current_epoch=8)
    update = BuilderUpdate("u1", "s1", "status", 0, a8, {"message": "building"})
    assert lifecycle.publish_update(update, actor=a8, current_epoch=8) is True
    preview = BuilderResource("preview", "p1", a8, {"url": "http://127.0.0.1/preview"})
    lifecycle.put_resource(preview, session_id="s1", actor=a8, current_epoch=8)

    orphan_action = BuilderActionReceipt("a2", "missing", "test", "queued", a8, {})
    must_fail(lambda: lifecycle.record_action(orphan_action, actor=a8, current_epoch=8))
    orphan_update = BuilderUpdate("u2", "missing", "console", 0, a8, {})
    must_fail(lambda: lifecycle.publish_update(orphan_update, actor=a8, current_epoch=8))
    orphan_resource = BuilderResource("diff", "d1", a8, {})
    must_fail(
        lambda: lifecycle.put_resource(
            orphan_resource, session_id="missing", actor=a8, current_epoch=8
        )
    )

    forged = BuilderActionReceipt("a3", "s1", "build", "queued", b8, {})
    must_fail(lambda: lifecycle.record_action(forged, actor=a8, current_epoch=8))
    must_fail(lambda: lifecycle.open_session("global", actor=normal, current_epoch=0, payload={}))
    must_fail(lambda: lifecycle.publish_update(update, actor=a8, current_epoch=9))
    must_fail(
        lambda: lifecycle.put_resource(
            BuilderResource("session", "s2", a8, {}),
            session_id="s1",
            actor=a8,
            current_epoch=8,
        )
    )

    removed = lifecycle.revoke_stale_epoch(authority=a8, current_epoch=8)
    assert removed["resources"] >= 1
    assert lifecycle.resources.get(
        "s1", request=a8, current_epoch=8, resource_type="session"
    ) is not None
    assert lifecycle.actions.get("a1", request=a8, current_epoch=8) is not None
    assert lifecycle.updates.list_readable(
        request=a8, current_epoch=8, session_id="s1"
    )[0].update_id == "u1"


if __name__ == "__main__":
    main()
