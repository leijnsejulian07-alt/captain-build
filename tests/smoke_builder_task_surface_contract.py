"""Regression: builder task pane is secret-free, project-scoped, and cannot bypass resume gates."""

from src.captain.builder_action_receipts import BuilderActionReceipt
from src.captain.builder_connector_bridge import BuilderConnectorBridge
from src.captain.builder_job_recovery import BuilderJobCheckpoint
from src.captain.builder_lifecycle import BuilderLifecycleCoordinator
from src.captain.builder_restart_manifest import export_restart_manifest
from src.captain.builder_startup_registry import BuilderStartupRegistry
from src.captain.builder_task_surface import BuilderTaskSurface
from src.captain.connector_settings import (
    AuthMethod,
    ConnectorHealth,
    ConnectorSettingsRegistry,
    ConnectorState,
)
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
    raise AssertionError("expected fail-closed builder task surface error")


def manifest(gateway, authority, session_id, job_id):
    lifecycle = BuilderLifecycleCoordinator()
    builder = ContextBoundBuilder(gateway=gateway, lifecycle=lifecycle)
    start = builder.open_session(
        session_id,
        request=authority,
        current_epoch=authority.state_epoch,
        capabilities=("files.read", "tests.run"),
        payload={"provider": "generic-builder", "secret": "must-not-leak"},
    )
    builder.record_action(
        start,
        BuilderActionReceipt(f"plan-{job_id}", session_id, "plan", "succeeded", authority, {}),
        current_epoch=authority.state_epoch,
    )
    builder.record_action(
        start,
        BuilderActionReceipt(f"build-{job_id}", session_id, "build", "running", authority, {}),
        current_epoch=authority.state_epoch,
    )
    lifecycle.checkpoint_job(
        BuilderJobCheckpoint(job_id, session_id, authority, "build", "running", attempt=1, sequence=2),
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


def add_memory(store, authority, record_id):
    store.put(
        MemoryContextRecord(
            record_id=record_id,
            kind="memory",
            payload={"value": record_id},
            scope=ScopedRecord(authority=authority),
        ),
        actor=authority,
        current_epoch=authority.state_epoch,
    )


def connector(project_id):
    return ConnectorState(
        connector_id="generic-builder-provider",
        project_id=project_id,
        installed=True,
        connected=True,
        enabled=True,
        auth_method=AuthMethod.LOCAL,
        health=ConnectorHealth.UNKNOWN,
    )


def main() -> None:
    a = ProjectAuthority("chat-a", "project-a", "repo-a", 12)
    b = ProjectAuthority("chat-b", "project-b", "repo-b", 12)
    memory = EpochBoundMemoryContextStore()
    add_memory(memory, a, "memory-a")
    add_memory(memory, b, "memory-b")
    gateway = RequestContextGateway(ContextAssembler(memory))

    startup = BuilderStartupRegistry(gateway=gateway)
    startup.recover(manifest(gateway, a, "shared-session", "job-a"), request=a, current_epoch=12)
    startup.recover(manifest(gateway, b, "shared-session", "job-b"), request=b, current_epoch=12)

    settings = ConnectorSettingsRegistry()
    settings.put(connector("project-a"))
    settings.put(connector("project-b"))
    bridge = BuilderConnectorBridge(startup=startup, settings=settings)
    bridge.bind("shared-session", "generic-builder-provider", request=a, current_epoch=12)
    bridge.bind("shared-session", "generic-builder-provider", request=b, current_epoch=12)
    surface = BuilderTaskSurface(startup=startup, bridge=bridge)

    # Restart-left work is paused and displayed only inside its owning project.
    snap_a = surface.snapshot(request=a, current_epoch=12)
    snap_b = surface.snapshot(request=b, current_epoch=12)
    assert [row.job_id for row in snap_a.rows] == ["job-a"]
    assert [row.job_id for row in snap_b.rows] == ["job-b"]
    assert snap_a.rows[0].job_status == "paused"
    assert snap_a.rows[0].reconnect_label == "Reconnect needed"
    assert not snap_a.rows[0].resume_allowed
    assert "must-not-leak" not in repr(snap_a.safe_payload())

    # UI resume cannot bypass disconnected/blocked provider state.
    must_fail(lambda: surface.resume("shared-session", "job-a", request=a, current_epoch=12))
    bridge.set_reconnect_status(
        "shared-session",
        "blocked",
        request=a,
        current_epoch=12,
        blocker="Reconnect in Settings",
    )
    blocked = surface.snapshot(request=a, current_epoch=12).rows[0]
    assert blocked.reconnect_label == "Blocked"
    assert blocked.settings_deep_link == "settings://connectors/generic-builder-provider"
    assert not blocked.resume_allowed
    must_fail(lambda: surface.resume("shared-session", "job-a", request=a, current_epoch=12))

    # Ready provider + Ready canonical connector exposes Resume and delegates to the bridge gate.
    bridge.set_reconnect_status("shared-session", "ready", request=a, current_epoch=12)
    ready = surface.snapshot(request=a, current_epoch=12).rows[0]
    assert ready.reconnect_label == "Ready"
    assert ready.resume_allowed
    after_resume = surface.resume("shared-session", "job-a", request=a, current_epoch=12)
    assert after_resume.rows[0].job_status == "running"
    assert not after_resume.rows[0].resume_allowed

    # Connector auth failure overrides provider-ready UI and blocks B without affecting A ownership.
    settings.update_health(
        "generic-builder-provider",
        project_id="project-b",
        health=ConnectorHealth.AUTH_INVALID,
    )
    bridge.set_reconnect_status("shared-session", "ready", request=b, current_epoch=12)
    auth_blocked = surface.snapshot(request=b, current_epoch=12).rows[0]
    assert auth_blocked.reconnect_label == "Blocked"
    assert auth_blocked.connector_health == ConnectorHealth.AUTH_INVALID.value
    assert not auth_blocked.resume_allowed
    must_fail(lambda: surface.resume("shared-session", "job-b", request=b, current_epoch=12))

    # Repo/epoch/normal-chat authority walls remain fail-closed at the UI edge.
    must_fail(
        lambda: surface.snapshot(
            request=ProjectAuthority("chat-a", "project-a", "repo-other", 12),
            current_epoch=12,
        )
    )
    must_fail(lambda: surface.snapshot(request=a, current_epoch=13))
    must_fail(lambda: surface.snapshot(request=ProjectAuthority(), current_epoch=12))

    print("PASS: builder task pane is project-safe, secret-free, and resume-gated")


if __name__ == "__main__":
    main()
