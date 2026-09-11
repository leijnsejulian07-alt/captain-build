"""Regression: builder reconnect state is projected into canonical Settings safely."""

from src.captain.builder_action_receipts import BuilderActionReceipt
from src.captain.builder_connector_bridge import BuilderConnectorBridge
from src.captain.builder_job_recovery import BuilderJobCheckpoint
from src.captain.builder_lifecycle import BuilderLifecycleCoordinator
from src.captain.builder_restart_manifest import export_restart_manifest
from src.captain.builder_startup_registry import BuilderStartupRegistry
from src.captain.connector_settings import (
    AuthMethod,
    ConnectorError,
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
    except (AuthorityError, ConnectorError):
        return
    raise AssertionError("expected fail-closed builder/connector error")


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
        payload={"provider": "generic-builder", "volatile_handle": "never-persist"},
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
    a = ProjectAuthority("chat-a", "project-a", "repo-a", 8)
    b = ProjectAuthority("chat-b", "project-b", "repo-b", 8)
    memory = EpochBoundMemoryContextStore()
    put_memory(memory, a, "m-a", "alpha")
    put_memory(memory, b, "m-b", "beta")
    gateway = RequestContextGateway(ContextAssembler(memory))

    startup = BuilderStartupRegistry(gateway=gateway)
    startup.recover(make_manifest(gateway, a, "same-provider-session", "job-a"), request=a, current_epoch=8)
    startup.recover(make_manifest(gateway, b, "same-provider-session", "job-b"), request=b, current_epoch=8)

    settings = ConnectorSettingsRegistry()
    settings.put(connector("project-a"))
    settings.put(connector("project-b"))
    bridge = BuilderConnectorBridge(startup=startup, settings=settings)

    # Same provider-local session and connector ids remain isolated by full authority.
    status_a = bridge.bind(
        "same-provider-session", "generic-builder-provider", request=a, current_epoch=8
    )
    status_b = bridge.bind(
        "same-provider-session", "generic-builder-provider", request=b, current_epoch=8
    )
    assert status_a.project_id == "project-a"
    assert status_b.project_id == "project-b"
    assert not status_a.resume_allowed
    assert not status_b.resume_allowed

    # A blocked reconnect drives the existing Settings remediation notice only in B.
    blocked = bridge.set_reconnect_status(
        "same-provider-session",
        "blocked",
        request=b,
        current_epoch=8,
        blocker="Reconnect provider in Captain Settings",
    )
    assert blocked.connector_health is ConnectorHealth.DEGRADED
    assert not blocked.resume_allowed
    assert settings.visible_notices(project_id="project-a", now=100.0) == ()
    notices_b = settings.visible_notices(project_id="project-b", now=100.0)
    assert len(notices_b) == 1
    assert notices_b[0].settings_deep_link == "settings://connectors/generic-builder-provider"
    assert "never-persist" not in repr(blocked.safe_payload())
    must_fail(
        lambda: bridge.resume_job(
            "same-provider-session", "job-b", request=b, current_epoch=8
        )
    )

    # Successful reconnect clears the same canonical notice and permits resume UX.
    ready_b = bridge.set_reconnect_status(
        "same-provider-session", "ready", request=b, current_epoch=8
    )
    assert ready_b.connector_health is ConnectorHealth.HEALTHY
    assert ready_b.connector_ready
    assert ready_b.resume_allowed
    assert settings.visible_notices(project_id="project-b", now=100.0) == ()
    resumed_b = bridge.resume_job(
        "same-provider-session", "job-b", request=b, current_epoch=8
    )
    assert resumed_b.status == "running"
    assert resumed_b.attempt == 2
    assert resumed_b.sequence >= 4

    # Specific Settings health failures are never hidden by generic builder-ready state.
    settings.update_health(
        "generic-builder-provider",
        project_id="project-a",
        health=ConnectorHealth.AUTH_INVALID,
    )
    ready_a = bridge.set_reconnect_status(
        "same-provider-session", "ready", request=a, current_epoch=8
    )
    assert ready_a.connector_health is ConnectorHealth.AUTH_INVALID
    assert not ready_a.connector_ready
    assert not ready_a.resume_allowed
    assert len(settings.visible_notices(project_id="project-a", now=100.0)) == 1
    must_fail(
        lambda: bridge.resume_job(
            "same-provider-session", "job-a", request=a, current_epoch=8
        )
    )

    # Cross-project/repo/epoch and normal-chat paths fail closed.
    must_fail(
        lambda: bridge.sync(
            "same-provider-session",
            request=ProjectAuthority("chat-a", "project-a", "repo-other", 8),
            current_epoch=8,
        )
    )
    must_fail(
        lambda: bridge.sync("same-provider-session", request=a, current_epoch=9)
    )
    must_fail(
        lambda: bridge.bind(
            "same-provider-session",
            "generic-builder-provider",
            request=ProjectAuthority(),
            current_epoch=8,
        )
    )

    print("PASS: builder reconnect and job resume are project-safe in canonical Connector Settings")


if __name__ == "__main__":
    main()
