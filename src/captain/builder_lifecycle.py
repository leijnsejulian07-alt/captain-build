"""Captain-owned lifecycle boundary for OpenBuilder sessions and outputs.

This coordinator composes the existing epoch-bound resource, action, update and
background-job stores. Adapters should cross this boundary instead of publishing
handles or results directly: every action/update/resource/job must belong to a
live Captain session in the same chat/project/repository/Project-State epoch.
Builder phase ordering is also Captain-owned so adapters cannot skip verification
gates or resume durable work under a different authority/session.
"""

from __future__ import annotations

from typing import Mapping, Optional

from .builder_action_receipts import BuilderActionReceipt, EpochBoundBuilderActionLedger
from .builder_job_recovery import BuilderJobCheckpoint, EpochBoundBuilderJobStore
from .builder_phase_machine import BuilderPhaseStateMachine
from .builder_resource_store import BuilderResource, EpochBoundBuilderResourceStore
from .builder_update_stream import BuilderUpdate, EpochBoundBuilderUpdateStream
from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch


class BuilderLifecycleCoordinator:
    """Single Captain control-plane boundary for an OpenBuilder lifecycle."""

    def __init__(
        self,
        *,
        resources: Optional[EpochBoundBuilderResourceStore] = None,
        actions: Optional[EpochBoundBuilderActionLedger] = None,
        updates: Optional[EpochBoundBuilderUpdateStream] = None,
        phases: Optional[BuilderPhaseStateMachine] = None,
        jobs: Optional[EpochBoundBuilderJobStore] = None,
    ) -> None:
        self.resources = resources or EpochBoundBuilderResourceStore()
        self.actions = actions or EpochBoundBuilderActionLedger()
        self.updates = updates or EpochBoundBuilderUpdateStream()
        self.phases = phases or BuilderPhaseStateMachine()
        self.jobs = jobs or EpochBoundBuilderJobStore()

    @staticmethod
    def _validate_actor(actor: ProjectAuthority, *, current_epoch: int) -> None:
        actor.validate()
        if actor.is_normal_chat:
            raise AuthorityError("OpenBuilder lifecycle requires project authority")
        require_current_epoch(actor, current_epoch=current_epoch)

    def open_session(
        self,
        session_id: str,
        *,
        actor: ProjectAuthority,
        current_epoch: int,
        payload: Mapping[str, object],
    ) -> BuilderResource:
        self._validate_actor(actor, current_epoch=current_epoch)
        existing = self.resources.get(
            session_id,
            request=actor,
            current_epoch=current_epoch,
            resource_type="session",
        )
        if existing is not None:
            raise AuthorityError("builder session is already open")

        session = BuilderResource("session", session_id, actor, payload)
        self.resources.put(session, actor=actor, current_epoch=current_epoch)
        stored = self.resources.get(
            session_id,
            request=actor,
            current_epoch=current_epoch,
            resource_type="session",
        )
        assert stored is not None
        self.phases.open_session(authority=actor, session_id=session_id)
        return stored

    def _require_session(
        self,
        session_id: str,
        *,
        actor: ProjectAuthority,
        current_epoch: int,
    ) -> BuilderResource:
        self._validate_actor(actor, current_epoch=current_epoch)
        session = self.resources.get(
            session_id,
            request=actor,
            current_epoch=current_epoch,
            resource_type="session",
        )
        if session is None:
            raise AuthorityError("builder output requires a live Captain-owned session")
        return session

    def record_action(
        self,
        receipt: BuilderActionReceipt,
        *,
        actor: ProjectAuthority,
        current_epoch: int,
    ) -> None:
        actor.require_same_owner(receipt.authority)
        self._require_session(receipt.session_id, actor=actor, current_epoch=current_epoch)
        self.phases.validate_receipt(receipt)
        self.actions.record(receipt, actor=actor, current_epoch=current_epoch)
        self.phases.apply_receipt(receipt)

    def publish_update(
        self,
        update: BuilderUpdate,
        *,
        actor: ProjectAuthority,
        current_epoch: int,
    ) -> bool:
        actor.require_same_owner(update.authority)
        self._require_session(update.session_id, actor=actor, current_epoch=current_epoch)
        return self.updates.publish(update, actor=actor, current_epoch=current_epoch)

    def put_resource(
        self,
        resource: BuilderResource,
        *,
        session_id: str,
        actor: ProjectAuthority,
        current_epoch: int,
    ) -> None:
        if resource.resource_type == "session":
            raise AuthorityError("session resources must be created through open_session")
        actor.require_same_owner(resource.authority)
        self._require_session(session_id, actor=actor, current_epoch=current_epoch)
        self.phases.require_resource(
            authority=actor,
            session_id=session_id,
            resource_type=resource.resource_type,
        )
        self.resources.put(resource, actor=actor, current_epoch=current_epoch)

    def checkpoint_job(
        self,
        checkpoint: BuilderJobCheckpoint,
        *,
        actor: ProjectAuthority,
        current_epoch: int,
    ) -> BuilderJobCheckpoint:
        """Persist job progress only for a live session under the exact authority."""
        actor.require_same_owner(checkpoint.authority)
        self._require_session(checkpoint.session_id, actor=actor, current_epoch=current_epoch)
        return self.jobs.put(checkpoint, actor=actor, current_epoch=current_epoch)

    def resume_job(
        self,
        job_id: str,
        *,
        actor: ProjectAuthority,
        current_epoch: int,
    ) -> BuilderJobCheckpoint:
        """Explicitly resume durable work after re-validating its owning session."""
        checkpoint = self.jobs.get(job_id, request=actor, current_epoch=current_epoch)
        if checkpoint is None:
            raise AuthorityError("unknown builder job")
        self._require_session(checkpoint.session_id, actor=actor, current_epoch=current_epoch)
        return self.jobs.resume(job_id, request=actor, current_epoch=current_epoch)

    def recover_interrupted_jobs(
        self,
        *,
        actor: ProjectAuthority,
        current_epoch: int,
    ) -> int:
        """On restart, pause crash-left running jobs; never auto-resume them."""
        self._validate_actor(actor, current_epoch=current_epoch)
        return self.jobs.recover_interrupted(
            authority=actor,
            current_epoch=current_epoch,
        )

    def revoke_stale_epoch(
        self,
        *,
        authority: ProjectAuthority,
        current_epoch: int,
    ) -> Mapping[str, int]:
        """Clean stale state across all builder stores after an epoch transition."""
        self._validate_actor(authority, current_epoch=current_epoch)
        return {
            "resources": self.resources.revoke_epoch(
                authority=authority, current_epoch=current_epoch
            ),
            "actions": self.actions.revoke_epoch(
                authority=authority, current_epoch=current_epoch
            ),
            "updates": self.updates.revoke_epoch(
                authority=authority, current_epoch=current_epoch
            ),
            "phases": self.phases.revoke_epoch(authority=authority),
            "jobs": self.jobs.revoke_epoch(
                authority=authority, current_epoch=current_epoch
            ),
        }
