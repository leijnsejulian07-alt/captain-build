"""Secret-free builder/task-pane projection for Captain's desktop Control Center.

This module owns no lifecycle, auth, job, connector, or notification state. It reads
validated recovered sessions from BuilderStartupRegistry and connector readiness through
BuilderConnectorBridge, then emits project-scoped rows suitable for Captain's task pane.
The only mutating action, resume, delegates to the bridge's canonical resume gate so UI
code cannot bypass provider reconnect + Connector Settings readiness checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .builder_connector_bridge import BuilderConnectorBridge
from .builder_startup_registry import BuilderStartupRegistry
from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch

_RESUMABLE_JOB_STATUSES = frozenset({"queued", "paused", "failed"})
_RECONNECT_LABELS = {
    "disconnected": "Reconnect needed",
    "reconnecting": "Connecting",
    "ready": "Ready",
    "blocked": "Blocked",
}


@dataclass(frozen=True)
class BuilderTaskRow:
    session_id: str
    connector_id: str
    job_id: str
    phase: str
    job_status: str
    reconnect_status: str
    reconnect_label: str
    connector_ready: bool
    connector_health: str
    settings_deep_link: str
    resume_allowed: bool

    def safe_payload(self) -> dict:
        return {
            "session_id": self.session_id,
            "connector_id": self.connector_id,
            "job_id": self.job_id,
            "phase": self.phase,
            "job_status": self.job_status,
            "reconnect_status": self.reconnect_status,
            "reconnect_label": self.reconnect_label,
            "connector_ready": self.connector_ready,
            "connector_health": self.connector_health,
            "settings_deep_link": self.settings_deep_link,
            "resume_allowed": self.resume_allowed,
        }


@dataclass(frozen=True)
class BuilderTaskPaneSnapshot:
    project_id: str
    rows: Tuple[BuilderTaskRow, ...]

    def safe_payload(self) -> dict:
        return {
            "project_id": self.project_id,
            "rows": [row.safe_payload() for row in self.rows],
        }


class BuilderTaskSurface:
    """Read-only UI projection with a single delegated resume action."""

    def __init__(
        self,
        *,
        startup: BuilderStartupRegistry,
        bridge: BuilderConnectorBridge,
    ) -> None:
        if type(startup) is not BuilderStartupRegistry:
            raise AuthorityError("builder task surface requires canonical startup registry")
        if type(bridge) is not BuilderConnectorBridge:
            raise AuthorityError("builder task surface requires canonical connector bridge")
        self._startup = startup
        self._bridge = bridge

    @staticmethod
    def _validate_request(request: ProjectAuthority, *, current_epoch: int) -> None:
        request.validate()
        if request.is_normal_chat:
            raise AuthorityError("builder task surface requires project authority")
        require_current_epoch(request, current_epoch=current_epoch)

    def snapshot(
        self,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> BuilderTaskPaneSnapshot:
        self._validate_request(request, current_epoch=current_epoch)
        assert request.project_id is not None
        rows = []
        for entry in self._startup.sessions_for(request=request, current_epoch=current_epoch):
            status = self._bridge.sync(
                entry.session_id,
                request=request,
                current_epoch=current_epoch,
            )
            records = entry.recovered.lifecycle.jobs.export_state(
                request=request,
                current_epoch=current_epoch,
            )
            for job in records:
                if job["session_id"] != entry.session_id:
                    raise AuthorityError("builder task projection encountered cross-session job")
                job_status = job["status"]
                resume_allowed = (
                    status.resume_allowed and job_status in _RESUMABLE_JOB_STATUSES
                )
                label = _RECONNECT_LABELS[status.reconnect_status]
                if status.reconnect_status == "ready" and not status.connector_ready:
                    label = "Blocked"
                rows.append(
                    BuilderTaskRow(
                        session_id=entry.session_id,
                        connector_id=status.connector_id,
                        job_id=job["job_id"],
                        phase=job["phase"],
                        job_status=job_status,
                        reconnect_status=status.reconnect_status,
                        reconnect_label=label,
                        connector_ready=status.connector_ready,
                        connector_health=status.connector_health.value,
                        settings_deep_link=status.settings_deep_link,
                        resume_allowed=resume_allowed,
                    )
                )
        rows.sort(key=lambda row: (row.session_id, row.job_id))
        return BuilderTaskPaneSnapshot(project_id=request.project_id, rows=tuple(rows))

    def resume(
        self,
        session_id: str,
        job_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> BuilderTaskPaneSnapshot:
        """Resume only through BuilderConnectorBridge, then return fresh UI state."""
        self._validate_request(request, current_epoch=current_epoch)
        self._bridge.resume_job(
            session_id,
            job_id,
            request=request,
            current_epoch=current_epoch,
        )
        return self.snapshot(request=request, current_epoch=current_epoch)
