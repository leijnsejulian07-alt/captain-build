"""Regression: realtime builder updates must obey current Project State epoch walls."""

from __future__ import annotations

from types import MappingProxyType

from src.captain.builder_update_stream import BuilderUpdate, EpochBoundBuilderUpdateStream
from src.captain.project_authority import AuthorityError, ProjectAuthority


def expect_denied(fn, needle: str = "") -> None:
    try:
        fn()
    except AuthorityError as exc:
        if needle and needle not in str(exc):
            raise AssertionError(f"expected {needle!r} in {exc!r}")
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
    assert stream.publish(first, actor=owner, current_epoch=7) is False

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

    # Provider-local update IDs may safely repeat across authority walls.
    assert stream.publish(BuilderUpdate("same-id", "session-b", "status", 0, other_project, {"state": "b"}), actor=other_project, current_epoch=7)
    assert stream.publish(BuilderUpdate("same-id", "session-c", "status", 0, other_repo, {"state": "c"}), actor=other_repo, current_epoch=7)
    assert stream.publish(BuilderUpdate("same-id", "session-d", "status", 0, owner, {"state": "a"}), actor=owner, current_epoch=7)
    assert stream.list_readable(request=owner, current_epoch=7, session_id="session-d")[0].payload["state"] == "a"
    assert stream.list_readable(request=other_project, current_epoch=7, session_id="session-b")[0].payload["state"] == "b"

    # Replays/out-of-order events and changed content inside one authority fail closed.
    expect_denied(lambda: stream.publish(BuilderUpdate("u-3", "session-a", "debug", 1, owner, {}), actor=owner, current_epoch=7))
    expect_denied(lambda: stream.publish(BuilderUpdate("u-1", "session-a", "console", 0, owner, {"line": "changed"}), actor=owner, current_epoch=7), "immutable")

    # Payloads are immutable snapshots, not caller-owned mutable references.
    caller_payload = {"nested": {"files": ["a.py"]}}
    assert stream.publish(BuilderUpdate("snapshot", "session-snapshot", "artifact", 0, owner, caller_payload), actor=owner, current_epoch=7)
    caller_payload["nested"]["files"].append("evil.py")
    snapshot = stream.list_readable(request=owner, current_epoch=7, session_id="session-snapshot")[0]
    assert isinstance(snapshot.payload, MappingProxyType)
    assert snapshot.payload["nested"]["files"] == ("a.py",)
    try:
        snapshot.payload["x"] = "mutate"
    except TypeError:
        pass
    else:
        raise AssertionError("stored builder update payload must be immutable")

    # Unsafe/custom payloads, NaN, event kinds and malformed filters fail closed.
    class Hostile:
        pass

    expect_denied(lambda: stream.publish(BuilderUpdate("bad-object", "session-x", "status", 0, owner, {"x": Hostile()}), actor=owner, current_epoch=7), "unsupported")
    expect_denied(lambda: stream.publish(BuilderUpdate("bad-nan", "session-y", "status", 0, owner, {"x": float("nan")}), actor=owner, current_epoch=7), "non-finite")
    expect_denied(lambda: stream.publish(BuilderUpdate("u-bad", "session-z", "arbitrary", 0, owner, {}), actor=owner, current_epoch=7))
    expect_denied(lambda: stream.list_readable(request=owner, current_epoch=7, session_id=""))
    expect_denied(lambda: stream.list_readable(request=owner, current_epoch=7, after_sequence=-2))
    expect_denied(lambda: stream.list_readable(request=ProjectAuthority("chat-a", "project-a", None, 7), current_epoch=7))

    # Cleanup of an old epoch is owner-local and not a replacement for authorization.
    legacy_key = stream._storage_key(stale, "legacy")
    other_stale = ProjectAuthority("chat-a", "project-b", "repo-a", 6)
    other_legacy_key = stream._storage_key(other_stale, "other-legacy")
    stream._updates[legacy_key] = BuilderUpdate("legacy", "session-old", "status", 0, stale, MappingProxyType({"state": "old"}))
    stream._last_sequence[(stale, "session-old")] = 0
    stream._updates[other_legacy_key] = BuilderUpdate("other-legacy", "session-old", "status", 0, other_stale, MappingProxyType({}))
    stream._last_sequence[(other_stale, "session-old")] = 0
    assert stream.revoke_epoch(authority=owner, current_epoch=7) == 1
    assert legacy_key not in stream._updates
    assert other_legacy_key in stream._updates

    print("BUILDER_UPDATE_STREAM_EPOCH_PASS")


if __name__ == "__main__":
    main()
