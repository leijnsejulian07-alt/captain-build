"""Regression for durable OpenBuilder causal phase recovery."""
from src.captain.builder_action_receipts import BuilderActionReceipt
from src.captain.builder_phase_machine import BuilderPhaseStateMachine
from src.captain.project_authority import AuthorityError, ProjectAuthority


def must_fail(fn, message: str) -> None:
    try:
        fn()
        raise AssertionError(message)
    except AuthorityError:
        pass


def receipt(action_id: str, phase: str, status: str, authority: ProjectAuthority) -> BuilderActionReceipt:
    return BuilderActionReceipt(action_id, "session-1", phase, status, authority, {})


def main() -> None:
    a = ProjectAuthority("chat-a", "project-a", "repo-a", 8)
    b = ProjectAuthority("chat-b", "project-b", "repo-b", 8)
    stale = ProjectAuthority("chat-a", "project-a", "repo-a", 7)

    phases = BuilderPhaseStateMachine()
    phases.open_session(authority=a, session_id="session-1")
    phases.apply_receipt(receipt("plan-1", "plan", "succeeded", a))
    phases.apply_receipt(receipt("build-1", "build", "succeeded", a))
    phases.apply_receipt(receipt("test-1", "test", "succeeded", a))
    phases.apply_receipt(receipt("review-1", "review", "failed", a))

    exported = phases.export_state(authority=a, session_id="session-1", current_epoch=8)
    assert set(exported) == {
        "session_id", "chat_id", "project_id", "repo_scope", "state_epoch",
        "completed", "attempted", "failed_phase", "actions",
    }
    assert exported["completed"] == ["build", "plan", "test"]
    assert exported["failed_phase"] == "review"
    assert exported["actions"]["review-1"] == "review"

    # Simulated restart: causal gates survive rehydration instead of resetting.
    restarted = BuilderPhaseStateMachine()
    restarted.restore_state(dict(exported), authority=a, current_epoch=8)
    restarted.apply_receipt(receipt("debug-1", "debug", "succeeded", a))
    must_fail(
        lambda: restarted.apply_receipt(receipt("preview-early", "preview", "succeeded", a)),
        "preview bypassed test/review after recovered debug",
    )
    restarted.apply_receipt(receipt("test-2", "test", "succeeded", a))
    restarted.apply_receipt(receipt("review-2", "review", "succeeded", a))
    restarted.apply_receipt(receipt("preview-1", "preview", "succeeded", a))

    # Restore is exact-owner/current-epoch only and cannot overwrite a live session.
    must_fail(
        lambda: BuilderPhaseStateMachine().restore_state(dict(exported), authority=stale, current_epoch=8),
        "stale phase checkpoint restored",
    )
    must_fail(
        lambda: BuilderPhaseStateMachine().restore_state(dict(exported), authority=b, current_epoch=8),
        "cross-project phase checkpoint restored",
    )
    must_fail(
        lambda: phases.restore_state(dict(exported), authority=a, current_epoch=8),
        "phase restore overwrote live session",
    )

    # Persisted state is schema-checked and cannot invent causal success.
    injected = dict(exported)
    injected["token"] = "secret"
    must_fail(
        lambda: BuilderPhaseStateMachine().restore_state(injected, authority=a, current_epoch=8),
        "unexpected persisted field accepted",
    )
    impossible = dict(exported)
    impossible["completed"] = ["build", "plan", "preview", "test"]
    impossible["attempted"] = ["build", "plan", "preview", "test"]
    must_fail(
        lambda: BuilderPhaseStateMachine().restore_state(impossible, authority=a, current_epoch=8),
        "forged preview success accepted without review",
    )
    duplicate = dict(exported)
    duplicate["attempted"] = list(exported["attempted"]) + ["review"]
    must_fail(
        lambda: BuilderPhaseStateMachine().restore_state(duplicate, authority=a, current_epoch=8),
        "duplicate persisted phase accepted",
    )

    print("BUILDER_PHASE_RECOVERY_PASS")


if __name__ == "__main__":
    main()
