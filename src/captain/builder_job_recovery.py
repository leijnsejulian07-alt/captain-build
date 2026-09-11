"""Epoch-bound persistence contract for Captain/OpenBuilder background jobs.

The store is deliberately storage-backend agnostic: callers may persist the
secret-free exported records to Captain's durable job store and restore them
after restart.  Restore/resume always re-validates complete ProjectAuthority,
Project State epoch and immutable session/phase identity before work can run.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Iterable, Mapping, Optional, Tuple

from .builder_phase_machine import BUILDER_PHASES
from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch

JOB_STATUSES = frozenset({"queued", "running", "paused", "succeeded", "failed", "cancelled"})
_RESUMABLE_STATUSES = frozenset({"queued", "paused", "failed"})
_ALLOWED_TRANSITIONS = {
    "queued": frozenset({"queued", "running", "cancelled"}),
    "running": frozenset({"running", "paused", "succeeded", "failed", "cancelled"}),
    "paused": frozenset({"paused", "queued", "running", "cancelled"}),
    "failed": frozenset({"failed", "queued", "running", "cancelled"}),
    "succeeded": frozenset({"succeeded"}),
    "cancelled": frozenset({"cancelled"}),
}

BuilderJobKey = Tuple[str, str, str, int, str]


@dataclass(frozen=True)
class BuilderJobCheckpoint:
    job_id: str
    session_id: str
    authority: ProjectAuthority
    phase: str
    status: str
    attempt: int = 0
    sequence: int = 0

    def validate(self) -> "BuilderJobCheckpoint":
        self.authority.validate()
        if self.authority.is_normal_chat:
            raise AuthorityError("builder jobs require project authority")
        if not isinstance(self.job_id, str) or not self.job_id.strip():
            raise AuthorityError("builder job requires a non-empty job_id")
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise AuthorityError("builder job requires a non-empty session_id")
        if self.phase not in BUILDER_PHASES:
            raise AuthorityError("builder job phase is not recognized")
        if self.status not in JOB_STATUSES:
            raise AuthorityError("builder job status is not recognized")
        if type(self.attempt) is not int or self.attempt < 0:
            raise AuthorityError("builder job attempt must be a non-negative integer")
        if type(self.sequence) is not int or self.sequence < 0:
            raise AuthorityError("builder job sequence must be a non-negative integer")
        return self

    def safe_payload(self) -> dict:
        self.validate()
        return {
            "job_id": self.job_id,
            "session_id": self.session_id,
            "chat_id": self.authority.chat_id,
            "project_id": self.authority.project_id,
            "repo_scope": self.authority.repo_scope,
            "state_epoch": self.authority.state_epoch,
            "phase": self.phase,
            "status": self.status,
            "attempt": self.attempt,
            "sequence": self.sequence,
        }


class EpochBoundBuilderJobStore:
    """Fail-closed checkpoint/resume boundary for persistent builder jobs."""

    def __init__(self) -> None:
        self._jobs: Dict[BuilderJobKey, BuilderJobCheckpoint] = {}

    @staticmethod
    def _key(authority: ProjectAuthority, job_id: str) -> BuilderJobKey:
        authority.validate()
        if authority.is_normal_chat:
            raise AuthorityError("normal chat cannot own builder jobs")
        if not isinstance(job_id, str) or not job_id.strip():
            raise AuthorityError("builder job requires a non-empty job_id")
        assert authority.chat_id is not None
        assert authority.project_id is not None
        assert authority.repo_scope is not None
        assert authority.state_epoch is not None
        return (
            authority.chat_id,
            authority.project_id,
            authority.repo_scope,
            authority.state_epoch,
            job_id,
        )

    @staticmethod
    def _validate_actor(actor: ProjectAuthority, *, current_epoch: int) -> None:
        actor.validate()
        if actor.is_normal_chat:
            raise AuthorityError("normal chat cannot access builder jobs")
        require_current_epoch(actor, current_epoch=current_epoch)

    def put(
        self,
        checkpoint: BuilderJobCheckpoint,
        *,
        actor: ProjectAuthority,
        current_epoch: int,
    ) -> BuilderJobCheckpoint:
        self._validate_actor(actor, current_epoch=current_epoch)
        checkpoint.validate()
        actor.require_same_owner(checkpoint.authority)
        key = self._key(actor, checkpoint.job_id)
        previous = self._jobs.get(key)
        if previous is not None:
            if previous.session_id != checkpoint.session_id or previous.phase != checkpoint.phase:
                raise AuthorityError("builder job session/phase identity cannot change")
            if checkpoint.sequence < previous.sequence:
                raise AuthorityError("builder job sequence cannot move backwards")
            if checkpoint.attempt < previous.attempt:
                raise AuthorityError("builder job attempt cannot move backwards")
            if checkpoint.status not in _ALLOWED_TRANSITIONS[previous.status]:
                raise AuthorityError("invalid builder job status transition")
            if checkpoint.sequence == previous.sequence and checkpoint != previous:
                raise AuthorityError("builder job mutation requires a new sequence")
        self._jobs[key] = checkpoint
        return checkpoint

    def get(
        self,
        job_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> Optional[BuilderJobCheckpoint]:
        self._validate_actor(request, current_epoch=current_epoch)
        checkpoint = self._jobs.get(self._key(request, job_id))
        if checkpoint is None:
            return None
        checkpoint.validate()
        request.require_same_owner(checkpoint.authority)
        return checkpoint

    def resume(
        self,
        job_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> BuilderJobCheckpoint:
        checkpoint = self.get(job_id, request=request, current_epoch=current_epoch)
        if checkpoint is None:
            raise AuthorityError("unknown builder job")
        if checkpoint.status not in _RESUMABLE_STATUSES:
            raise AuthorityError("builder job is not in a resumable state")
        resumed = replace(
            checkpoint,
            status="running",
            attempt=checkpoint.attempt + 1,
            sequence=checkpoint.sequence + 1,
        )
        return self.put(resumed, actor=request, current_epoch=current_epoch)

    def recover_interrupted(
        self,
        *,
        authority: ProjectAuthority,
        current_epoch: int,
    ) -> int:
        """Convert crash-left running work to paused before any explicit resume."""
        self._validate_actor(authority, current_epoch=current_epoch)
        changed = 0
        for key, checkpoint in tuple(self._jobs.items()):
            if checkpoint.authority.same_owner(authority) and checkpoint.status == "running":
                self._jobs[key] = replace(
                    checkpoint,
                    status="paused",
                    sequence=checkpoint.sequence + 1,
                )
                changed += 1
        return changed

    def export_state(
        self,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> Tuple[dict, ...]:
        """Return secret-free canonical records suitable for Captain persistence."""
        self._validate_actor(request, current_epoch=current_epoch)
        records = [
            checkpoint.safe_payload()
            for checkpoint in self._jobs.values()
            if checkpoint.authority.same_owner(request)
        ]
        records.sort(key=lambda item: item["job_id"])
        return tuple(records)

    def restore_state(
        self,
        records: Iterable[Mapping[str, object]],
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> int:
        """Restore only exact current-owner/current-epoch canonical checkpoint rows."""
        self._validate_actor(request, current_epoch=current_epoch)
        count = 0
        expected_keys = {
            "job_id", "session_id", "chat_id", "project_id", "repo_scope",
            "state_epoch", "phase", "status", "attempt", "sequence",
        }
        for raw in records:
            if type(raw) is not dict:
                raise AuthorityError("builder job restore rows must be canonical dicts")
            if set(raw) != expected_keys:
                raise AuthorityError("builder job restore row has unexpected fields")
            authority = ProjectAuthority(
                chat_id=raw["chat_id"],
                project_id=raw["project_id"],
                repo_scope=raw["repo_scope"],
                state_epoch=raw["state_epoch"],
            )
            request.require_same_owner(authority)
            checkpoint = BuilderJobCheckpoint(
                job_id=raw["job_id"],
                session_id=raw["session_id"],
                authority=authority,
                phase=raw["phase"],
                status=raw["status"],
                attempt=raw["attempt"],
                sequence=raw["sequence"],
            )
            self.put(checkpoint, actor=request, current_epoch=current_epoch)
            count += 1
        return count

    def revoke_epoch(
        self,
        *,
        authority: ProjectAuthority,
        current_epoch: int,
    ) -> int:
        self._validate_actor(authority, current_epoch=current_epoch)
        doomed = [
            key
            for key, checkpoint in self._jobs.items()
            if checkpoint.authority.chat_id == authority.chat_id
            and checkpoint.authority.project_id == authority.project_id
            and checkpoint.authority.repo_scope == authority.repo_scope
            and checkpoint.authority.state_epoch != authority.state_epoch
        ]
        for key in doomed:
            del self._jobs[key]
        return len(doomed)
