"""Regression: restart checkpoints stay bound to Captain's exact context."""

from src.captain.builder_action_receipts import BuilderActionReceipt
from src.captain.builder_job_recovery import BuilderJobCheckpoint
from src.captain.builder_lifecycle import BuilderLifecycleCoordinator
from src.captain.builder_restart_manifest import export_restart_manifest, verify_restart_context
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


def put(store, authority, record_id, value):
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
    store = EpochBoundMemoryContextStore()
    put(store, authority, "m1", "original")
    put(store, other, "m1", "other")
    gateway = RequestContextGateway(ContextAssembler(store))
    lifecycle = BuilderLifecycleCoordinator()
    builder = ContextBoundBuilder(gateway=gateway, lifecycle=lifecycle)

    started = builder.open_session(
        "s1", request=authority, current_epoch=8,
        capabilities=("files.read", "tests.run"), payload={"provider": "openbuilder"},
    )
    builder.record_action(
        started,
        BuilderActionReceipt("plan-1", "s1", "plan", "succeeded", authority, {}),
        current_epoch=8,
    )
    lifecycle.checkpoint_job(
        BuilderJobCheckpoint("job-1", "s1", authority, "build", "queued"),
        actor=authority, current_epoch=8,
    )

    manifest = export_restart_manifest(
        session_id="s1", context=started.context, phases=lifecycle.phases,
        jobs=lifecycle.jobs, current_epoch=8,
    )
    payload = manifest.safe_payload()
    restored = verify_restart_context(
        payload, gateway=gateway, request=authority, current_epoch=8
    )
    assert restored.authority == authority
    assert restored.capabilities == ("files.read", "tests.run")
    assert "original" not in repr(payload)
    assert payload["jobs"][0]["job_id"] == "job-1"

    # Context changed within the same epoch: never silently resume against it.
    put(store, authority, "m2", "new-context")
    must_fail(
        lambda: verify_restart_context(
            payload, gateway=gateway, request=authority, current_epoch=8
        )
    )

    # Owner, repo and epoch are part of the proof, not advisory metadata.
    must_fail(lambda: verify_restart_context(payload, gateway=gateway, request=other, current_epoch=8))
    must_fail(lambda: verify_restart_context(payload, gateway=gateway, request=authority, current_epoch=9))
    forged = dict(payload)
    forged["context_sha256"] = "0" * 64
    must_fail(lambda: verify_restart_context(forged, gateway=gateway, request=authority, current_epoch=8))
    extra = dict(payload)
    extra["unexpected"] = True
    must_fail(lambda: verify_restart_context(extra, gateway=gateway, request=authority, current_epoch=8))

    # A durable non-queued job cannot claim a phase the causal checkpoint never attempted.
    clean_store = EpochBoundMemoryContextStore()
    put(clean_store, authority, "m1", "original")
    clean_gateway = RequestContextGateway(ContextAssembler(clean_store))
    broken_lifecycle = BuilderLifecycleCoordinator()
    broken_builder = ContextBoundBuilder(gateway=clean_gateway, lifecycle=broken_lifecycle)
    broken = broken_builder.open_session("s2", request=authority, current_epoch=8, payload={})
    broken_lifecycle.jobs.put(
        BuilderJobCheckpoint("job-x", "s2", authority, "test", "running"),
        actor=authority, current_epoch=8,
    )
    must_fail(
        lambda: export_restart_manifest(
            session_id="s2", context=broken.context, phases=broken_lifecycle.phases,
            jobs=broken_lifecycle.jobs, current_epoch=8,
        )
    )

    print("PASS: builder restart manifest is context-bound and causally consistent")


if __name__ == "__main__":
    main()
