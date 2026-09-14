from __future__ import annotations

import hashlib

from parking.integration.builder_output_handles import AccessDenied, BuilderOutputHandleStore
from parking.integration.project_epoch_transition import EpochTransitionError, apply_project_epoch_transition


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class CleanupProbe:
    def __init__(self, count: int = 0, *, fail: bool = False, invalid: object | None = None) -> None:
        self.count = count
        self.fail = fail
        self.invalid = invalid
        self.calls: list[tuple[str, str, str, int]] = []

    def revoke_stale_epochs(self, *, chat_id: str, project_id: str, repo_scope: str, current_epoch: int) -> int:
        self.calls.append((chat_id, project_id, repo_scope, current_epoch))
        if self.fail:
            raise RuntimeError("probe failure")
        if self.invalid is not None:
            return self.invalid  # type: ignore[return-value]
        return self.count


def expect_error(fn) -> None:
    try:
        fn()
        raise AssertionError("expected EpochTransitionError")
    except EpochTransitionError:
        pass


def main() -> None:
    store = BuilderOutputHandleStore(b"x" * 32)
    common = dict(chat_id="chat-a", project_id="proj-a", repo_scope="repo-a", builder_session_id="build-1", revision=1)
    stale = store.issue(kind="preview", epoch=1, artifact_digest=digest("old"), **common)
    current = store.issue(kind="preview", epoch=2, artifact_digest=digest("new"), **common)
    other = store.issue(kind="preview", chat_id="chat-a", project_id="proj-b", repo_scope="repo-b", epoch=1,
                        builder_session_id="build-2", revision=1, artifact_digest=digest("other"))
    sessions = CleanupProbe(2)
    context = CleanupProbe(3)

    result = apply_project_epoch_transition(
        chat_id="chat-a", project_id="proj-a", repo_scope="repo-a",
        previous_epoch=1, current_epoch=2, builder_outputs=store,
        additional_cleanups={"sessions": sessions, "context": context},
    )
    assert result.revoked_builder_handles == 1
    assert result.cleanup_counts == (("builder_outputs", 1), ("context", 3), ("sessions", 2))
    assert sessions.calls == [("chat-a", "proj-a", "repo-a", 2)]
    assert context.calls == [("chat-a", "proj-a", "repo-a", 2)]
    try:
        store.resolve(stale, expected_kind="preview", chat_id="chat-a", project_id="proj-a", repo_scope="repo-a",
                      current_epoch=2, builder_session_id="build-1")
        raise AssertionError("stale handle survived transition")
    except AccessDenied:
        pass
    assert store.resolve(current, expected_kind="preview", chat_id="chat-a", project_id="proj-a", repo_scope="repo-a",
                         current_epoch=2, builder_session_id="build-1")["epoch"] == 2
    assert store.resolve(other, expected_kind="preview", chat_id="chat-a", project_id="proj-b", repo_scope="repo-b",
                         current_epoch=1, builder_session_id="build-2")["epoch"] == 1

    # Cleanup is idempotent when the underlying cleanup adapters are idempotent.
    assert apply_project_epoch_transition(
        chat_id="chat-a", project_id="proj-a", repo_scope="repo-a",
        previous_epoch=1, current_epoch=2, builder_outputs=store,
    ).revoked_builder_handles == 0

    for previous, current_epoch in ((2, 2), (3, 2), (0, 1), (1, True)):
        expect_error(lambda previous=previous, current_epoch=current_epoch: apply_project_epoch_transition(
            chat_id="chat-a", project_id="proj-a", repo_scope="repo-a",
            previous_epoch=previous, current_epoch=current_epoch, builder_outputs=store,
        ))

    # Validate every dependency before any side effect so malformed configuration cannot
    # partially mutate one resource family before Captain notices another is unusable.
    untouched = CleanupProbe(9)
    expect_error(lambda: apply_project_epoch_transition(
        chat_id="chat-a", project_id="proj-a", repo_scope="repo-a", previous_epoch=2, current_epoch=3,
        builder_outputs=untouched, additional_cleanups={"bad name": CleanupProbe(1)},
    ))
    assert untouched.calls == []
    expect_error(lambda: apply_project_epoch_transition(
        chat_id="chat-a", project_id="proj-a", repo_scope="repo-a", previous_epoch=2, current_epoch=3,
        builder_outputs=untouched, additional_cleanups={"builder_outputs": CleanupProbe(1)},
    ))
    assert untouched.calls == []
    expect_error(lambda: apply_project_epoch_transition(
        chat_id="chat-a", project_id="proj-a", repo_scope="repo-a", previous_epoch=2, current_epoch=3,
        builder_outputs=untouched, additional_cleanups={"duplicate": untouched},
    ))
    assert untouched.calls == []

    invalid_result = CleanupProbe(invalid=True)
    expect_error(lambda: apply_project_epoch_transition(
        chat_id="chat-a", project_id="proj-a", repo_scope="repo-a", previous_epoch=2, current_epoch=3,
        builder_outputs=invalid_result,
    ))
    assert len(invalid_result.calls) == 1

    # Runtime cleanup failure is fail-closed. Earlier revocations are not restored because
    # re-authorizing stale resources would be less safe than a partially completed cleanup.
    primary = CleanupProbe(1)
    failing = CleanupProbe(fail=True)
    later = CleanupProbe(4)
    expect_error(lambda: apply_project_epoch_transition(
        chat_id="chat-a", project_id="proj-a", repo_scope="repo-a", previous_epoch=2, current_epoch=3,
        builder_outputs=primary, additional_cleanups={"a_failing": failing, "z_later": later},
    ))
    assert len(primary.calls) == 1
    assert len(failing.calls) == 1
    assert later.calls == []


if __name__ == "__main__":
    main()
