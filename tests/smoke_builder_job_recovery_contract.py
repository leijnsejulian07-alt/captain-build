"""Regression for persistent OpenBuilder job checkpoint/recovery isolation."""
from src.captain.builder_job_recovery import BuilderJobCheckpoint, EpochBoundBuilderJobStore
from src.captain.builder_lifecycle import BuilderLifecycleCoordinator
from src.captain.project_authority import AuthorityError, ProjectAuthority


def must_fail(fn, message: str) -> None:
    try:
        fn()
        raise AssertionError(message)
    except AuthorityError:
        pass


def main() -> None:
    a = ProjectAuthority("chat-a", "project-a", "repo-a", 4)
    b = ProjectAuthority("chat-b", "project-b", "repo-b", 4)
    stale = ProjectAuthority("chat-a", "project-a", "repo-a", 3)

    lifecycle = BuilderLifecycleCoordinator()
    lifecycle.open_session("session-1", actor=a, current_epoch=4, payload={"source": "captain"})
    lifecycle.open_session("session-1", actor=b, current_epoch=4, payload={"source": "captain"})

    queued = BuilderJobCheckpoint("job-1", "session-1", a, "build", "queued")
    lifecycle.checkpoint_job(queued, actor=a, current_epoch=4)
    running = BuilderJobCheckpoint("job-1", "session-1", a, "build", "running", sequence=1)
    lifecycle.checkpoint_job(running, actor=a, current_epoch=4)

    # Crash-left work is paused on recovery; Captain never silently auto-resumes it.
    assert lifecycle.recover_interrupted_jobs(actor=a, current_epoch=4) == 1
    paused = lifecycle.jobs.get("job-1", request=a, current_epoch=4)
    assert paused is not None and paused.status == "paused" and paused.sequence == 2
    resumed = lifecycle.resume_job("job-1", actor=a, current_epoch=4)
    assert resumed.status == "running" and resumed.attempt == 1 and resumed.sequence == 3

    # Provider-local job IDs may safely repeat across unrelated projects.
    other = BuilderJobCheckpoint("job-1", "session-1", b, "plan", "queued")
    lifecycle.checkpoint_job(other, actor=b, current_epoch=4)
    assert lifecycle.jobs.get("job-1", request=b, current_epoch=4) == other
    assert lifecycle.jobs.get("job-1", request=a, current_epoch=4) == resumed

    # Export is secret-free canonical persistence data and restores only exact owner+epoch.
    exported = lifecycle.jobs.export_state(request=a, current_epoch=4)
    assert len(exported) == 1
    assert set(exported[0]) == {
        "job_id", "session_id", "chat_id", "project_id", "repo_scope",
        "state_epoch", "phase", "status", "attempt", "sequence",
    }
    restored_store = EpochBoundBuilderJobStore()
    assert restored_store.restore_state(exported, request=a, current_epoch=4) == 1
    assert restored_store.get("job-1", request=a, current_epoch=4) == resumed

    # Simulated restart: restored running work must be paused before an explicit resume.
    restarted = BuilderLifecycleCoordinator(jobs=restored_store)
    restarted.open_session("session-1", actor=a, current_epoch=4, payload={"restored": True})
    assert restarted.recover_interrupted_jobs(actor=a, current_epoch=4) == 1
    resumed_again = restarted.resume_job("job-1", actor=a, current_epoch=4)
    assert resumed_again.status == "running" and resumed_again.attempt == 2

    # Cross-project, stale-epoch, orphan-session and schema-forgery paths fail closed.
    must_fail(
        lambda: lifecycle.resume_job("job-1", actor=stale, current_epoch=4),
        "stale job resumed",
    )
    orphan = BuilderJobCheckpoint("orphan", "missing-session", a, "build", "queued")
    must_fail(
        lambda: lifecycle.checkpoint_job(orphan, actor=a, current_epoch=4),
        "orphan job accepted",
    )
    forged = [dict(exported[0], project_id="project-b")]
    must_fail(
        lambda: EpochBoundBuilderJobStore().restore_state(forged, request=a, current_epoch=4),
        "cross-project persisted job restored",
    )
    injected = [dict(exported[0], token="secret")]
    must_fail(
        lambda: EpochBoundBuilderJobStore().restore_state(injected, request=a, current_epoch=4),
        "unexpected persisted field accepted",
    )

    # Session/phase identity and terminal status cannot be rewritten on replay.
    must_fail(
        lambda: lifecycle.checkpoint_job(
            BuilderJobCheckpoint("job-1", "session-1", a, "test", "running", attempt=1, sequence=4),
            actor=a,
            current_epoch=4,
        ),
        "job phase changed after creation",
    )
    lifecycle.checkpoint_job(
        BuilderJobCheckpoint("job-1", "session-1", a, "build", "succeeded", attempt=1, sequence=4),
        actor=a,
        current_epoch=4,
    )
    must_fail(
        lambda: lifecycle.resume_job("job-1", actor=a, current_epoch=4),
        "terminal job resumed",
    )

    print("BUILDER_JOB_RECOVERY_PASS")


if __name__ == "__main__":
    main()
