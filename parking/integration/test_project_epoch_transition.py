from __future__ import annotations

import hashlib

from parking.integration.builder_output_handles import AccessDenied, BuilderOutputHandleStore
from parking.integration.project_epoch_transition import EpochTransitionError, apply_project_epoch_transition


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def main() -> None:
    store = BuilderOutputHandleStore(b"x" * 32)
    common = dict(chat_id="chat-a", project_id="proj-a", repo_scope="repo-a", builder_session_id="build-1", revision=1)
    stale = store.issue(kind="preview", epoch=1, artifact_digest=digest("old"), **common)
    current = store.issue(kind="preview", epoch=2, artifact_digest=digest("new"), **common)
    other = store.issue(kind="preview", chat_id="chat-a", project_id="proj-b", repo_scope="repo-b", epoch=1,
                        builder_session_id="build-2", revision=1, artifact_digest=digest("other"))

    result = apply_project_epoch_transition(
        chat_id="chat-a", project_id="proj-a", repo_scope="repo-a",
        previous_epoch=1, current_epoch=2, builder_outputs=store,
    )
    assert result.revoked_builder_handles == 1
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

    assert apply_project_epoch_transition(
        chat_id="chat-a", project_id="proj-a", repo_scope="repo-a",
        previous_epoch=1, current_epoch=2, builder_outputs=store,
    ).revoked_builder_handles == 0
    for previous, current_epoch in ((2, 2), (3, 2), (0, 1), (1, True)):
        try:
            apply_project_epoch_transition(chat_id="chat-a", project_id="proj-a", repo_scope="repo-a",
                                           previous_epoch=previous, current_epoch=current_epoch, builder_outputs=store)
            raise AssertionError("invalid transition accepted")
        except EpochTransitionError:
            pass


if __name__ == "__main__":
    main()
