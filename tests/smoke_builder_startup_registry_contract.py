"""Regression: startup recovery is multi-project isolated and reconnect-gated."""

from src.captain.builder_action_receipts import BuilderActionReceipt
from src.captain.builder_job_recovery import BuilderJobCheckpoint
from src.captain.builder_lifecycle import BuilderLifecycleCoordinator
from src.captain.builder_restart_manifest import export_restart_manifest
from src.captain.builder_startup_registry import BuilderStartupRegistry
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


def make_manifest(gateway, authority, session_id, job_id):
    lifecycle = BuilderLifecycleCoordinator()
    builder = ContextBoundBuilder(gateway=gateway, lifecycle=lifecycle)
    start = builder.open_session(
        session_id,
        request=authority,
        current_epoch=authority.state_epoch,
        capabilities=("files.read", "tests.run"),
        payload={"provider": "openbuilder", "volatile_handle": "never-persist"},
    )
    builder.record_action(
        start,
        BuilderActionReceipt(
            f"plan-{job_id}", session_id, "plan", "succeeded", authority, {}
        ),
        current_epoch=authority.state_epoch,
    )
    builder.record_action(
        start,
        BuilderActionReceipt(
            f"build-{job_id}", session_id, "build", "running", authority, {}
        ),
        current_epoch=authority.state_epoch,
    )
    lifecycle.checkpoint_job(
        BuilderJobCheckpoint(
            job_id,
            session_id,
            authority,
            "build",
            "running",
            attempt=1,
            sequence=2,
        ),
        actor=authority,
        current_epoch=authority.state_epoch,
    )
    return export_restart_manifest(
        session_id=session_id,
        context=start.context,
        phases=lifecycle.phases,
        jobs=lifecycle.jobs,
        current_epoch=authority.state_epoch,
    ).safe_payload()


def main() -> None:
    a = ProjectAuthority("chat-a", "project-a", "repo-a", 8)
    b = ProjectAuthority("chat-b", "project-b", "repo-b", 8)
    normal = ProjectAuthority()
    memory = EpochBoundMemoryContextStore()
    put_memory(memory, a, "m-a", "alpha")
    put_memory(memory, b, "m-b", "beta")
    gateway = RequestContextGateway(ContextAssembler(memory))

    # The same provider-local session id is safe in unrelated projects.
    manifest_a = make_manifest(gateway, a, "provider-session-1", "job-a")
    manifest_b = make_manifest(gateway, b, "provider-session-1", "job-b")
    registry = BuilderStartupRegistry(gateway=gateway)
    entry_a = registry.recover(manifest_a, request=a, current_epoch=8)
    entry_b = registry.recover(manifest_b, request=b, current_epoch=8)
    assert entry_a.reconnect_status == "disconnected"
    assert entry_b.reconnect_status == "disconnected"
    assert entry_a.recovered.paused_jobs == 1
    assert entry_b.recovered.paused_jobs == 1

    # Recovery never implies provider reconnect and jobs cannot silently resume.
    must_fail(
        lambda: registry.resume_job(
            "provider-session-1", "job-a", request=a, current_epoch=8
        )
    )
    reconnecting = registry.set_reconnect_status(
        "provider-session-1", "reconnecting", request=a, current_epoch=8
    )
    assert reconnecting.reconnect_status == "reconnecting"
    must_fail(
        lambda: registry.resume_job(
            "provider-session-1", "job-a", request=a, current_epoch=8
        )
    )
    ready = registry.set_reconnect_status(
        "provider-session-1", "ready", request=a, current_epoch=8
    )
    assert ready.reconnect_blocker is None
    resumed = registry.resume_job(
        "provider-session-1", "job-a", request=a, current_epoch=8
    )
    assert resumed.status == "running"
    assert resumed.attempt == 2

    # A blocked provider exposes remediation state but never credentials/handles.
    blocked = registry.set_reconnect_status(
        "provider-session-1",
        "blocked",
        request=b,
        current_epoch=8,
        blocker="Reconnect provider in Captain Settings",
    )
    assert blocked.reconnect_status == "blocked"
    assert blocked.reconnect_blocker == "Reconnect provider in Captain Settings"
    assert "never-persist" not in repr(blocked)

    # Exact authority walls apply to reads, listings, job resume and duplicate recovery.
    assert registry.sessions_for(request=a, current_epoch=8) == (ready,)
    assert registry.sessions_for(request=b, current_epoch=8) == (blocked,)
    must_fail(
        lambda: registry.get("provider-session-1", request=ProjectAuthority(
            "chat-a", "project-a", "repo-other", 8
        ), current_epoch=8)
    )
    must_fail(lambda: registry.sessions_for(request=normal, current_epoch=8))
    must_fail(lambda: registry.recover(manifest_a, request=a, current_epoch=8))
    must_fail(
        lambda: registry.get("provider-session-1", request=a, current_epoch=9)
    )

    # One project's ready reconnect cannot authorize another project's job.
    must_fail(
        lambda: registry.resume_job(
            "provider-session-1", "job-b", request=a, current_epoch=8
        )
    )
    must_fail(
        lambda: registry.resume_job(
            "provider-session-1", "job-b", request=b, current_epoch=8
        )
    )

    print("PASS: multi-project builder startup is isolated and reconnect-gated")


if __name__ == "__main__":
    main()
