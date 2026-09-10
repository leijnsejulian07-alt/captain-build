"""Regression: realtime builder updates must obey current Project State epoch walls."""

from __future__ import annotations

from src.captain.builder_update_stream import BuilderUpdate, EpochBoundBuilderUpdateStream
from src.captain.project_authority import AuthorityError, ProjectAuthority


def expect_denied(fn) -> None:
    try:
        fn()
    except AuthorityError:
        return
    raise AssertionError("expected fail-closed AuthorityError")


def main() -> None:
    stream = EpochBoundBuilderUpdateStream()
    owner = ProjectAuthority("chat-a", "project-a", "repo-a", 7)
    stale = ProjectAuthority("chat-a", "project-a", "repo-a", 6)
    future = ProjectAuthority("chat-a", "project-a", "repo-a", 8)
    other_chat = ProjectAuthority("chat-b", "project-a", "repo-a", 7)
    other_project = ProjectAuthority("chat-a", "project-b", "repo-a", 7)
    other_repo = ProjectAuthority("chat-a", "project-a", "repo-b", 7)
    normal_chat = ProjectAuthority()

    first = BuilderUpdate("u-1", "session-a", "console", 0, owner, {"line": "build started"})
    assert stream.publish(first, actor=owner, current_epoch=7) is True
    assert stream.publish(first, actor=owner, current_epoch=7) is False  # idempotent retry

    second = BuilderUpdate("u-2", "session-a", "preview", 1, owner, {"url": "local-preview"})
    assert stream.publish(second, actor=owner, current_epoch=7) is True
    assert [u.update_id for u in stream.list_readable(request=owner, current_epoch=7)] == ["u-1", "u-2"]
    assert [u.update_id for u in stream.list_readable(request=owner, current_epoch=7, after_sequence=0)] == ["u-2"]

    # Normal chat and stale/future actors cannot touch builder streams.
    expect_denied(lambda: stream.list_readable(request=normal_chat, current_epoch=7))
    expect_denied(lambda: stream.publish(BuilderUpdate("u-stale", "session-a", "console", 2, stale, {}), actor=stale, current_epoch=7))
    expect_denied(lambda: stream.publish(BuilderUpdate("u-future", "session-a", "console", 2, future, {}), actor=future, current_epoch=7))

    # Cross-wall reads return nothing, while forged writes fail closed.
    assert stream.list_readable(request=other_chat, current_epoch=7) == []
    assert stream.list_readable(request=other_project, current_epoch=7) == []
    assert stream.list_readable(request=other_repo, current_epoch=7) == []
    expect_denied(lambda: stream.publish(BuilderUpdate("u-forged", "session-a", "test", 2, owner, {}), actor=other_project, current_epoch=7))

    # Replays/out-of-order events and mutable update IDs are rejected.
    expect_denied(lambda: stream.publish(BuilderUpdate("u-3", "session-a", "debug", 1, owner, {}), actor=owner, current_epoch=7))
    expect_denied(lambda: stream.publish(BuilderUpdate("u-1", "session-a", "console", 0, owner, {"line": "changed"}), actor=owner, current_epoch=7))
    expect_denied(lambda: stream.publish(BuilderUpdate("u-1", "session-a", "console", 0, other_project, {}), actor=other_project, current_epoch=7))

    # Unknown event types, malformed filters and partial authority fail closed.
    expect_denied(lambda: stream.publish(BuilderUpdate("u-bad", "session-a", "arbitrary", 2, owner, {}), actor=owner, current_epoch=7))
    expect_denied(lambda: stream.list_readable(request=owner, current_epoch=7, session_id=""))
    expect_denied(lambda: stream.list_readable(request=owner, current_epoch=7, after_sequence=-2))
    expect_denied(lambda: stream.list_readable(request=ProjectAuthority("chat-a", "project-a", None, 7), current_epoch=7))

    # Cleanup of an old epoch is owner-local and not a replacement for authorization.
    stream._updates["legacy"] = BuilderUpdate("legacy", "session-old", "status", 0, stale, {"state": "old"})
    stream._last_sequence[(stale, "session-old")] = 0
    other_stale = ProjectAuthority("chat-a", "project-b", "repo-a", 6)
    stream._updates["other-legacy"] = BuilderUpdate("other-legacy", "session-old", "status", 0, other_stale, {})
    stream._last_sequence[(other_stale, "session-old")] = 0
    assert stream.revoke_epoch(authority=owner, current_epoch=7) == 1
    assert "legacy" not in stream._updates
    assert "other-legacy" in stream._updates

    print("BUILDER_UPDATE_STREAM_EPOCH_PASS")


if __name__ == "__main__":
    main()
