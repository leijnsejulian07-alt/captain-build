from __future__ import annotations

import hashlib

from parking.integration.builder_output_handles import BuilderOutputHandleStore
from parking.integration.builder_pane_access import BuilderPaneAccessGate
from parking.integration.builder_pane_state import BuilderPaneStateContract, PaneAccessDenied

SECRET = b"p" * 32
HANDLE_SECRET = b"h" * 32
SCOPE = dict(chat_id="chat-a", project_id="project-a", repo_scope="repo-a")
SID = "builder-1"
EPOCH = 7
REV = 3


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def make_fixture(revision: int = REV):
    store = BuilderOutputHandleStore(HANDLE_SECRET)
    handles = {k: None for k in ("file", "diff", "console", "test", "preview", "rollback")}
    handles["preview"] = store.issue(
        kind="preview",
        epoch=EPOCH,
        builder_session_id=SID,
        revision=revision,
        artifact_digest=digest(f"preview-{revision}"),
        now=100,
        **SCOPE,
    )
    contract = BuilderPaneStateContract(SECRET)
    state = contract.issue(
        epoch=EPOCH,
        builder_session_id=SID,
        revision=REV,
        handles=handles,
        **SCOPE,
    )
    return store, handles, contract, state


def expect_denied(fn):
    try:
        fn()
    except PaneAccessDenied:
        return
    raise AssertionError("expected PaneAccessDenied")


def main() -> None:
    store, handles, contract, state = make_fixture()
    gate = BuilderPaneAccessGate(contract, store)
    result = gate.resolve(
        state.public(), kind="preview", current_epoch=EPOCH,
        builder_session_id=SID, current_revision=REV, handles=handles, now=100, **SCOPE,
    )
    assert set(result) == {"handle_id", "kind", "revision", "artifact_digest", "expires_at"}
    assert result["kind"] == "preview" and result["revision"] == REV

    expect_denied(lambda: gate.resolve(
        state.public(), kind="preview", current_epoch=EPOCH + 1,
        builder_session_id=SID, current_revision=REV, handles=handles, now=100, **SCOPE,
    ))
    expect_denied(lambda: gate.resolve(
        state.public(), kind="preview", current_epoch=EPOCH,
        builder_session_id="builder-2", current_revision=REV, handles=handles, now=100, **SCOPE,
    ))
    expect_denied(lambda: gate.resolve(
        state.public(), kind="preview", current_epoch=EPOCH,
        builder_session_id=SID, current_revision=REV, handles=handles, now=100,
        chat_id="chat-b", project_id="project-a", repo_scope="repo-a",
    ))
    expect_denied(lambda: gate.resolve(
        state.public(), kind="build", current_epoch=EPOCH,
        builder_session_id=SID, current_revision=REV, handles=handles, now=100, **SCOPE,
    ))
    expect_denied(lambda: gate.resolve(
        state.public(), kind="file", current_epoch=EPOCH,
        builder_session_id=SID, current_revision=REV, handles=handles, now=100, **SCOPE,
    ))

    # Crucial regression: the generic handle store permits >= min_revision, while the
    # interactive pane must reject a newer artifact under an older pane revision.
    newer_store, newer_handles, newer_contract, newer_state = make_fixture(REV + 1)
    newer_gate = BuilderPaneAccessGate(newer_contract, newer_store)
    expect_denied(lambda: newer_gate.resolve(
        newer_state.public(), kind="preview", current_epoch=EPOCH,
        builder_session_id=SID, current_revision=REV, handles=newer_handles, now=100, **SCOPE,
    ))

    # A handle substitution invalidates the signed pane snapshot before resolution.
    replacement = store.issue(
        kind="preview", epoch=EPOCH, builder_session_id=SID, revision=REV,
        artifact_digest=digest("replacement"), now=100, **SCOPE,
    )
    swapped = dict(handles)
    swapped["preview"] = replacement
    expect_denied(lambda: gate.resolve(
        state.public(), kind="preview", current_epoch=EPOCH,
        builder_session_id=SID, current_revision=REV, handles=swapped, now=100, **SCOPE,
    ))

    print("BUILDER_PANE_ACCESS_PASS")


if __name__ == "__main__":
    main()
