from __future__ import annotations

import copy

from parking.integration.builder_pane_state import (
    BuilderPaneStateContract,
    PaneAccessDenied,
    PaneStateError,
    PANE_KINDS,
)

SECRET = b"p" * 32
SCOPE = dict(chat_id="chatA", project_id="projectA", repo_scope="owner/repo@main")
SID = "builder-session-1"
EPOCH = 7
REVISION = 4


def _handle(seed: str) -> str:
    a = (seed.encode().hex() + "0" * 32)[:32]
    b = (seed[::-1].encode().hex() + "1" * 32)[:32]
    return f"boh1.{a}.{b}"


def _handles() -> dict[str, str | None]:
    return {
        "file": _handle("file"),
        "diff": _handle("diff"),
        "console": _handle("console"),
        "test": _handle("test"),
        "preview": _handle("preview"),
        "rollback": _handle("rollback"),
    }


def _deny(fn) -> None:
    try:
        fn()
    except PaneAccessDenied:
        return
    raise AssertionError("expected fail-closed PaneAccessDenied")


def main() -> None:
    c = BuilderPaneStateContract(SECRET)
    handles = _handles()
    state = c.issue(**SCOPE, epoch=EPOCH, builder_session_id=SID, revision=REVISION, handles=handles)

    validated = c.validate(
        state,
        **SCOPE,
        current_epoch=EPOCH,
        builder_session_id=SID,
        current_revision=REVISION,
        handles=handles,
    )
    assert validated["epoch"] == EPOCH
    assert validated["revision"] == REVISION

    public = state.public()
    text = repr(public)
    assert SCOPE["chat_id"] not in text
    assert SCOPE["project_id"] not in text
    assert SCOPE["repo_scope"] not in text
    assert SID not in text
    for value in handles.values():
        assert value not in text

    _deny(lambda: c.validate(state, **SCOPE, current_epoch=EPOCH + 1, builder_session_id=SID, current_revision=REVISION, handles=handles))
    _deny(lambda: c.validate(state, chat_id="chatB", project_id=SCOPE["project_id"], repo_scope=SCOPE["repo_scope"], current_epoch=EPOCH, builder_session_id=SID, current_revision=REVISION, handles=handles))
    _deny(lambda: c.validate(state, chat_id=SCOPE["chat_id"], project_id="projectB", repo_scope=SCOPE["repo_scope"], current_epoch=EPOCH, builder_session_id=SID, current_revision=REVISION, handles=handles))
    _deny(lambda: c.validate(state, chat_id=SCOPE["chat_id"], project_id=SCOPE["project_id"], repo_scope="owner/other@main", current_epoch=EPOCH, builder_session_id=SID, current_revision=REVISION, handles=handles))
    _deny(lambda: c.validate(state, **SCOPE, current_epoch=EPOCH, builder_session_id="builder-session-2", current_revision=REVISION, handles=handles))
    _deny(lambda: c.validate(state, **SCOPE, current_epoch=EPOCH, builder_session_id=SID, current_revision=REVISION + 1, handles=handles))

    swapped = dict(handles)
    swapped["preview"] = _handle("newpreview")
    _deny(lambda: c.validate(state, **SCOPE, current_epoch=EPOCH, builder_session_id=SID, current_revision=REVISION, handles=swapped))

    missing = dict(handles)
    missing.pop("console")
    try:
        c.validate(state, **SCOPE, current_epoch=EPOCH, builder_session_id=SID, current_revision=REVISION, handles=missing)
    except PaneStateError:
        pass
    else:
        raise AssertionError("missing canonical pane kind must fail")

    extra = state.public()
    extra["unexpected"] = True
    _deny(lambda: c.validate(extra, **SCOPE, current_epoch=EPOCH, builder_session_id=SID, current_revision=REVISION, handles=handles))

    tampered = copy.deepcopy(state.public())
    tampered["revision"] = REVISION + 1
    _deny(lambda: c.validate(tampered, **SCOPE, current_epoch=EPOCH, builder_session_id=SID, current_revision=REVISION + 1, handles=handles))

    nullable = {kind: None for kind in PANE_KINDS}
    blank = c.issue(**SCOPE, epoch=EPOCH, builder_session_id=SID, revision=0, handles=nullable)
    c.validate(blank, **SCOPE, current_epoch=EPOCH, builder_session_id=SID, current_revision=0, handles=nullable)

    print("BUILDER_PANE_STATE_PASS")


if __name__ == "__main__":
    main()
