"""Atomic restart rehydration for one context-bound Captain builder session.

Recovery is staged into a fresh lifecycle. Persisted input is first verified
against Captain's current Project State epoch and canonical memory/context, then
session, causal phase state and durable jobs are reconstructed off to the side.
Nothing is exposed to callers until the complete bundle is coherent. Crash-left
running jobs are converted to paused before a usable session token is issued.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .builder_lifecycle import BuilderLifecycleCoordinator
from .builder_resource_store import BuilderResource
from .builder_restart_manifest import verify_restart_context
from .context_bound_builder import BuilderSessionStart, ContextBoundBuilder
from .project_authority import AuthorityError, ProjectAuthority
from .request_context_gateway import RequestContextGateway


@dataclass(frozen=True)
class RehydratedBuilderSession:
    """A fully validated restart bundle that is safe for Captain to activate."""

    builder: ContextBoundBuilder
    lifecycle: BuilderLifecycleCoordinator
    start: BuilderSessionStart
    paused_jobs: int


def rehydrate_restart_manifest(
    record: Mapping[str, object],
    *,
    gateway: RequestContextGateway,
    request: ProjectAuthority,
    current_epoch: int,
) -> RehydratedBuilderSession:
    """Stage and atomically expose one persisted builder lifecycle.

    The returned lifecycle is newly constructed. Any validation/restore error
    therefore discards all staged mutations with the stack frame; no caller-owned
    live lifecycle can be left half-restored. Provider-specific process/session
    handles are deliberately not persisted or recreated here. Adapters reconnect
    only after Captain has issued the recovered context-bound token.
    """
    if type(record) is not dict:
        raise AuthorityError("builder restart rehydration requires a canonical manifest")
    if type(gateway) is not RequestContextGateway:
        raise AuthorityError("builder restart rehydration requires canonical context gateway")

    # This reassembles memory/context and revalidates schema, nested phase/jobs,
    # owner/repository/epoch identity and the context digest before any staging.
    context = verify_restart_context(
        record,
        gateway=gateway,
        request=request,
        current_epoch=current_epoch,
    )
    session_id = record["session_id"]
    phase_state = record["phase_state"]
    job_rows = record["jobs"]
    assert isinstance(session_id, str)
    assert type(phase_state) is dict
    assert type(job_rows) is list

    # Build the whole recovered control-plane state in isolation. This is the
    # transaction boundary: failures below never mutate an existing lifecycle.
    lifecycle = BuilderLifecycleCoordinator()
    staged_session = BuilderResource(
        resource_type="session",
        resource_id=session_id,
        authority=context.authority,
        payload={"recovered": True},
    )
    lifecycle.resources.put(
        staged_session,
        actor=context.authority,
        current_epoch=current_epoch,
    )
    session = lifecycle.resources.get(
        session_id,
        request=context.authority,
        current_epoch=current_epoch,
        resource_type="session",
    )
    if session is None:
        raise AuthorityError("staged builder session disappeared during rehydration")

    lifecycle.phases.restore_state(
        phase_state,
        authority=context.authority,
        current_epoch=current_epoch,
    )
    restored_jobs = lifecycle.jobs.restore_state(
        job_rows,
        request=context.authority,
        current_epoch=current_epoch,
    )
    if restored_jobs != len(job_rows):
        raise AuthorityError("builder restart job restore was incomplete")

    # A process crash never proves provider work is still running. Pause first;
    # explicit resume later rechecks the live session and increments attempt/seq.
    paused_jobs = lifecycle.recover_interrupted_jobs(
        actor=context.authority,
        current_epoch=current_epoch,
    )

    # Re-export the restored causal state as a final internal consistency proof.
    restored_phase = lifecycle.phases.export_state(
        authority=context.authority,
        session_id=session_id,
        current_epoch=current_epoch,
    )
    if restored_phase != phase_state:
        raise AuthorityError("rehydrated builder phase state changed unexpectedly")
    for row in lifecycle.jobs.export_state(
        request=context.authority,
        current_epoch=current_epoch,
    ):
        if row["session_id"] != session_id:
            raise AuthorityError("rehydrated lifecycle contains a foreign builder job")

    builder = ContextBoundBuilder(gateway=gateway, lifecycle=lifecycle)
    start = builder._adopt_rehydrated_session(
        context=context,
        session=session,
        current_epoch=current_epoch,
    )
    return RehydratedBuilderSession(
        builder=builder,
        lifecycle=lifecycle,
        start=start,
        paused_jobs=paused_jobs,
    )
