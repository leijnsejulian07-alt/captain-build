"""Captain-owned startup registry for recovered builder sessions.

This module composes the existing atomic per-session restart rehydration into one
multi-project startup surface. It does not create a second router: Captain remains
the authority source and every lookup is keyed by the full project authority,
epoch and session id.

Recovered provider handles are intentionally absent. A recovered session starts
in ``disconnected`` state and durable work cannot resume until Captain records an
explicit successful provider reconnect.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Mapping, Tuple

from .builder_job_recovery import BuilderJobCheckpoint
from .builder_rehydration import RehydratedBuilderSession, rehydrate_restart_manifest
from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch
from .request_context_gateway import RequestContextGateway


_RECONNECT_STATES = frozenset({"disconnected", "reconnecting", "ready", "blocked"})


@dataclass(frozen=True)
class StartupSession:
    authority: ProjectAuthority
    session_id: str
    recovered: RehydratedBuilderSession
    reconnect_status: str = "disconnected"
    reconnect_blocker: str | None = None


class BuilderStartupRegistry:
    """Canonical startup/reconnect surface for multiple recovered projects."""

    def __init__(self, *, gateway: RequestContextGateway) -> None:
        if type(gateway) is not RequestContextGateway:
            raise AuthorityError("builder startup registry requires canonical context gateway")
        self._gateway = gateway
        self._sessions: Dict[Tuple[str, str, str, int, str], StartupSession] = {}

    @staticmethod
    def _key(
        authority: ProjectAuthority,
        session_id: str,
        *,
        current_epoch: int,
    ) -> Tuple[str, str, str, int, str]:
        authority.validate()
        if authority.is_normal_chat:
            raise AuthorityError("builder startup registry requires project authority")
        require_current_epoch(authority, current_epoch=current_epoch)
        if not isinstance(session_id, str) or not session_id.strip():
            raise AuthorityError("builder session id must be a non-empty string")
        assert authority.chat_id is not None
        assert authority.project_id is not None
        assert authority.repo_scope is not None
        assert authority.state_epoch is not None
        return (
            authority.chat_id,
            authority.project_id,
            authority.repo_scope,
            authority.state_epoch,
            session_id,
        )

    def recover(
        self,
        record: Mapping[str, object],
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> StartupSession:
        if type(record) is not dict:
            raise AuthorityError("builder startup recovery requires a canonical manifest")
        session_id = record.get("session_id")
        if not isinstance(session_id, str):
            raise AuthorityError("builder restart manifest is missing session identity")
        key = self._key(request, session_id, current_epoch=current_epoch)
        if key in self._sessions:
            raise AuthorityError("builder session is already registered at startup")

        recovered = rehydrate_restart_manifest(
            record,
            gateway=self._gateway,
            request=request,
            current_epoch=current_epoch,
        )
        request.require_same_owner(recovered.start.context.authority)
        if recovered.start.session.resource_id != session_id:
            raise AuthorityError("rehydrated builder session identity changed")

        entry = StartupSession(
            authority=request,
            session_id=session_id,
            recovered=recovered,
        )
        self._sessions[key] = entry
        return entry

    def get(
        self,
        session_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> StartupSession:
        key = self._key(request, session_id, current_epoch=current_epoch)
        entry = self._sessions.get(key)
        if entry is None:
            raise AuthorityError("unknown builder startup session")
        return entry

    def set_reconnect_status(
        self,
        session_id: str,
        status: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
        blocker: str | None = None,
    ) -> StartupSession:
        if status not in _RECONNECT_STATES:
            raise AuthorityError("invalid builder provider reconnect status")
        if status == "blocked":
            if not isinstance(blocker, str) or not blocker.strip():
                raise AuthorityError("blocked reconnect status requires remediation text")
        elif blocker is not None:
            raise AuthorityError("reconnect blocker is valid only for blocked status")

        entry = self.get(session_id, request=request, current_epoch=current_epoch)
        updated = replace(
            entry,
            reconnect_status=status,
            reconnect_blocker=blocker if status == "blocked" else None,
        )
        key = self._key(request, session_id, current_epoch=current_epoch)
        self._sessions[key] = updated
        return updated

    def resume_job(
        self,
        session_id: str,
        job_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> BuilderJobCheckpoint:
        entry = self.get(session_id, request=request, current_epoch=current_epoch)
        if entry.reconnect_status != "ready":
            raise AuthorityError("builder provider must reconnect successfully before job resume")
        checkpoint = entry.recovered.lifecycle.jobs.get(
            job_id,
            request=request,
            current_epoch=current_epoch,
        )
        if checkpoint is None or checkpoint.session_id != session_id:
            raise AuthorityError("builder job does not belong to startup session")
        return entry.recovered.lifecycle.resume_job(
            job_id,
            actor=request,
            current_epoch=current_epoch,
        )

    def sessions_for(
        self,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> tuple[StartupSession, ...]:
        request.validate()
        if request.is_normal_chat:
            raise AuthorityError("builder startup registry requires project authority")
        require_current_epoch(request, current_epoch=current_epoch)
        result = [
            entry
            for entry in self._sessions.values()
            if entry.authority.same_owner(request)
        ]
        return tuple(sorted(result, key=lambda item: item.session_id))
