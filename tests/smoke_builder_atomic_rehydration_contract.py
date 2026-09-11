"""Regression: builder restart rehydration is staged, context-bound and paused-first."""

from src.captain.builder_action_receipts import BuilderActionReceipt
from src.captain.builder_job_recovery import BuilderJobCheckpoint
from src.captain.builder_lifecycle import BuilderLifecycleCoordinator
from src.captain.builder_rehydration import rehydrate_restart_manifest
from src.captain.builder_restart_manifest import export_restart_manifest
from src.captain.context_assembly import ContextAssembler
from src.captain.context_bound_builder import ContextBoundBuilder
from src.captain.memory_context_store import EpochBoundMemoryContextStore, MemoryContextRecord
from src.captain.project_authority import AuthorityError, ProjectAuthority, ScopedRecord
from src.captain.request_context_gateway import RequestContextGateway


def must_fail(fn):
    try:
        fn()
    except AuthorityError:
        return
    raise AssertionError("expected fail-closed AuthorityError")


def put_memory(store, authority, record_id, value):
    store.put(
        MemoryContextRecord(
            record_id=record_id,
            kind="memory",
            payload={"value": value},
            scope=ScopedRecord(authority=authority),
        ),
        actor=authority,
        current_epoch=authority.state_epoch,
    )


def main() -> None:
    authority = ProjectAuthority("chat-a", "project-a", "repo-a", 8)
    other = ProjectAuthority("chat-b", "project-b", "repo-b", 8)
    memory = EpochBoundMemoryContextStore()
    put_memory(memory, authority, "m1", "stable-context")
    gateway = RequestContextGateway(ContextAssembler(memory))

    # Build a realistic crash checkpoint: plan succeeded, build was running.
    original_lifecycle = BuilderLifecycleCoordinator()
    original_builder = ContextBoundBuilder(gateway=gateway, lifecycle=original_lifecycle)
    original = original_builder.open_session(
        "session-1",
        request=authority,
        current_epoch=8,
        capabilities=("files.read", "tests.run"),
        payload={"provider": "openbuilder", "volatile_handle": "not-persisted"},
    )
    original_builder.record_action(
        original,
        BuilderActionReceipt(
            "plan-1", "session-1", "plan", "succeeded", authority, {}
        ),
        current_epoch=8,
    )
    original_builder.record_action(
        original,
        BuilderActionReceipt(
            "build-1", "session-1", "build", "running", authority, {}
        ),
        current_epoch=8,
    )
    original_lifecycle.checkpoint_job(
        BuilderJobCheckpoint(
            "job-build", "session-1", authority, "build", "running", attempt=1, sequence=4
        ),
        actor=authority,
        current_epoch=8,
    )
    manifest = export_restart_manifest(
        session_id="session-1",
        context=original.context,
        phases=original_lifecycle.phases,
        jobs=original_lifecycle.jobs,
        current_epoch=8,
    ).safe_payload()
    assert "volatile_handle" not in repr(manifest)
    assert "stable-context" not in repr(manifest)

    recovered = rehydrate_restart_manifest(
        manifest,
        gateway=gateway,
        request=authority,
        current_epoch=8,
    )
    assert recovered.start.context == original.context
    assert recovered.start.session.resource_id == "session-1"
    assert recovered.start.session.payload["recovered"] is True
    assert recovered.paused_jobs == 1

    paused = recovered.lifecycle.jobs.get(
        "job-build", request=authority, current_epoch=8
    )
    assert paused is not None
    assert paused.status == "paused"
    assert paused.attempt == 1
    assert paused.sequence == 5

    # Recovery creates a usable Captain token, but work resumes only explicitly.
    resumed = recovered.lifecycle.resume_job(
        "job-build", actor=authority, current_epoch=8
    )
    assert resumed.status == "running"
    assert resumed.attempt == 2
    assert resumed.sequence == 6
    recovered.builder.record_action(
        recovered.start,
        BuilderActionReceipt(
            "build-1", "session-1", "build", "succeeded", authority, {}
        ),
        current_epoch=8,
    )
    phase = recovered.lifecycle.phases.export_state(
        authority=authority, session_id="session-1", current_epoch=8
    )
    assert "build" in phase["completed"]

    # The persisted provider payload/handle is never revived by Captain recovery.
    assert recovered.start.session.payload == {"recovered": True}

    # Cross-project and stale-epoch manifests never produce a recovered bundle.
    must_fail(
        lambda: rehydrate_restart_manifest(
            manifest, gateway=gateway, request=other, current_epoch=8
        )
    )
    must_fail(
        lambda: rehydrate_restart_manifest(
            manifest, gateway=gateway, request=authority, current_epoch=9
        )
    )

    # Nested persisted state is untrusted; a forged job/session binding fails closed.
    forged = dict(manifest)
    forged["jobs"] = [dict(manifest["jobs"][0])]
    forged["jobs"][0]["session_id"] = "foreign-session"
    must_fail(
        lambda: rehydrate_restart_manifest(
            forged, gateway=gateway, request=authority, current_epoch=8
        )
    )

    # Even inside the same epoch, changed Captain memory/context invalidates resume.
    put_memory(memory, authority, "m2", "new-context")
    must_fail(
        lambda: rehydrate_restart_manifest(
            manifest, gateway=gateway, request=authority, current_epoch=8
        )
    )

    print("PASS: builder restart rehydration is atomic, context-bound and paused-first")


if __name__ == "__main__":
    main()
