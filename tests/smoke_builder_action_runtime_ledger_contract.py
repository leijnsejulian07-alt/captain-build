"""Runtime regression for Captain's epoch-bound OpenBuilder action ledger."""

from src.captain.builder_action_receipts import (
    BuilderActionReceipt,
    EpochBoundBuilderActionLedger,
)
from src.captain.project_authority import AuthorityError, ProjectAuthority


def must_fail(fn, needle: str = "") -> None:
    try:
        fn()
    except AuthorityError as exc:
        if needle:
            assert needle in str(exc)
        return
    raise AssertionError("operation should have failed closed")


def receipt(action_id: str, authority: ProjectAuthority, *, status: str = "running", session: str = "s-1") -> BuilderActionReceipt:
    return BuilderActionReceipt(
        action_id=action_id,
        session_id=session,
        action_type="build",
        status=status,
        authority=authority,
        payload={"summary": "safe non-secret result"},
    )


def main() -> None:
    ledger = EpochBoundBuilderActionLedger()
    a7 = ProjectAuthority("chat-a", "project-a", "repo-a", 7)
    a8 = ProjectAuthority("chat-a", "project-a", "repo-a", 8)
    other_chat = ProjectAuthority("chat-b", "project-a", "repo-a", 7)
    other_project = ProjectAuthority("chat-a", "project-b", "repo-a", 7)
    other_repo = ProjectAuthority("chat-a", "project-a", "repo-b", 7)

    ledger.record(receipt("act-1", a7), actor=a7, current_epoch=7)
    assert ledger.get("act-1", request=a7, current_epoch=7) is not None

    # Ownership dimensions fail closed and are not enumerable across walls.
    assert ledger.get("act-1", request=other_chat, current_epoch=7) is None
    assert ledger.get("act-1", request=other_project, current_epoch=7) is None
    assert ledger.get("act-1", request=other_repo, current_epoch=7) is None
    assert ledger.list_readable(request=other_project, current_epoch=7) == []

    # Partial/normal scopes cannot consume or create builder receipts.
    must_fail(lambda: ledger.get("act-1", request=ProjectAuthority(), current_epoch=7), "normal chat")
    must_fail(
        lambda: ledger.get(
            "act-1",
            request=ProjectAuthority("chat-a", "project-a", None, 7),
            current_epoch=7,
        ),
        "partial",
    )

    # Old and future authority cannot consume delayed builder results.
    must_fail(lambda: ledger.get("act-1", request=a7, current_epoch=8), "stale or future")
    must_fail(lambda: ledger.get("act-1", request=a8, current_epoch=7), "stale or future")

    # New epoch may clean old receipts for the same owner tuple only.
    ledger.record(receipt("act-other", other_project), actor=other_project, current_epoch=7)
    removed = ledger.revoke_epoch(authority=a8, current_epoch=8)
    assert removed == 1
    assert ledger.get("act-1", request=a8, current_epoch=8) is None
    assert ledger.get("act-other", request=other_project, current_epoch=7) is not None

    # Cross-wall action-id overwrite attempts are rejected.
    ledger.record(receipt("collision", a8), actor=a8, current_epoch=8)
    must_fail(
        lambda: ledger.record(receipt("collision", other_project), actor=other_project, current_epoch=7),
        "collision",
    )

    # Immutable action identity and terminal receipts cannot be rewritten/reopened.
    ledger.record(receipt("terminal", a8, status="succeeded"), actor=a8, current_epoch=8)
    must_fail(
        lambda: ledger.record(receipt("terminal", a8, status="running"), actor=a8, current_epoch=8),
        "final",
    )
    changed_identity = BuilderActionReceipt(
        action_id="terminal",
        session_id="s-2",
        action_type="build",
        status="succeeded",
        authority=a8,
        payload={},
    )
    must_fail(lambda: ledger.record(changed_identity, actor=a8, current_epoch=8), "identity")

    # Unknown statuses fail closed rather than silently becoming valid updates.
    must_fail(lambda: ledger.record(receipt("bad-status", a8, status="mystery"), actor=a8, current_epoch=8), "status")

    print("BUILDER_ACTION_RUNTIME_LEDGER_EPOCH_PASS")


if __name__ == "__main__":
    main()
