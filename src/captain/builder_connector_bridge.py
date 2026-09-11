"""Bridge recovered builder provider state into Captain's canonical Connector Settings.

The bridge is intentionally thin: it does not authenticate providers, own credentials,
resume jobs without Settings approval, or create another notification system. It only
projects the already validated BuilderStartupRegistry reconnect state into the existing
project-scoped ConnectorSettingsRegistry health/remediation surface.

A builder session must be explicitly bound to an already-registered project connector.
The bridge never invents authentication, marks a disconnected connector connected, or
activates a paid connector. Severe provider health states reported by Settings
(auth-invalid/deprecated/migration-required) are never masked by generic builder state.
Recovered job resume is exposed here as the canonical UI/control-surface path so both
provider reconnect state and Connector Settings readiness are required.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from .builder_job_recovery import BuilderJobCheckpoint
from .builder_startup_registry import BuilderStartupRegistry
from .connector_settings import (
    ConnectorError,
    ConnectorHealth,
    ConnectorSettingsRegistry,
)
from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch


_PRESERVE_HEALTH = frozenset(
    {
        ConnectorHealth.AUTH_INVALID,
        ConnectorHealth.DEPRECATED,
        ConnectorHealth.MIGRATION_REQUIRED,
    }
)


@dataclass(frozen=True)
class BuilderConnectorStatus:
    session_id: str
    connector_id: str
    project_id: str
    reconnect_status: str
    connector_ready: bool
    connector_health: ConnectorHealth
    settings_deep_link: str
    resume_allowed: bool

    def safe_payload(self) -> dict:
        return {
            "session_id": self.session_id,
            "connector_id": self.connector_id,
            "project_id": self.project_id,
            "reconnect_status": self.reconnect_status,
            "connector_ready": self.connector_ready,
            "connector_health": self.connector_health.value,
            "settings_deep_link": self.settings_deep_link,
            "resume_allowed": self.resume_allowed,
        }


class BuilderConnectorBridge:
    """Project-safe projection from builder startup state to Connector Settings."""

    def __init__(
        self,
        *,
        startup: BuilderStartupRegistry,
        settings: ConnectorSettingsRegistry,
    ) -> None:
        if type(startup) is not BuilderStartupRegistry:
            raise AuthorityError("builder connector bridge requires canonical startup registry")
        if type(settings) is not ConnectorSettingsRegistry:
            raise ConnectorError("builder connector bridge requires canonical connector settings registry")
        self._startup = startup
        self._settings = settings
        self._bindings: Dict[Tuple[str, str, str, int, str], str] = {}

    @staticmethod
    def _key(
        request: ProjectAuthority,
        session_id: str,
        *,
        current_epoch: int,
    ) -> Tuple[str, str, str, int, str]:
        request.validate()
        if request.is_normal_chat:
            raise AuthorityError("builder connector bridge requires project authority")
        require_current_epoch(request, current_epoch=current_epoch)
        if not isinstance(session_id, str) or not session_id.strip():
            raise AuthorityError("builder session id must be a non-empty string")
        assert request.chat_id is not None
        assert request.project_id is not None
        assert request.repo_scope is not None
        assert request.state_epoch is not None
        return (
            request.chat_id,
            request.project_id,
            request.repo_scope,
            request.state_epoch,
            session_id,
        )

    def bind(
        self,
        session_id: str,
        connector_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> BuilderConnectorStatus:
        key = self._key(request, session_id, current_epoch=current_epoch)
        self._startup.get(session_id, request=request, current_epoch=current_epoch)
        if not isinstance(connector_id, str) or not connector_id.strip():
            raise ConnectorError("connector_id must be non-empty")
        assert request.project_id is not None
        state = self._settings.get(connector_id, project_id=request.project_id)
        if state is None:
            raise ConnectorError(
                "builder provider must be registered in project-scoped Captain Settings before binding"
            )
        existing = self._bindings.get(key)
        if existing is not None and existing != connector_id:
            raise AuthorityError("builder session is already bound to a different connector")
        self._bindings[key] = connector_id
        return self.sync(session_id, request=request, current_epoch=current_epoch)

    def _binding(
        self,
        session_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> str:
        key = self._key(request, session_id, current_epoch=current_epoch)
        connector_id = self._bindings.get(key)
        if connector_id is None:
            raise AuthorityError("builder session has no connector binding")
        return connector_id

    def sync(
        self,
        session_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> BuilderConnectorStatus:
        entry = self._startup.get(session_id, request=request, current_epoch=current_epoch)
        connector_id = self._binding(
            session_id,
            request=request,
            current_epoch=current_epoch,
        )
        assert request.project_id is not None
        state = self._settings.get(connector_id, project_id=request.project_id)
        if state is None:
            raise ConnectorError("bound builder connector disappeared from Captain Settings")

        health = state.health
        if health not in _PRESERVE_HEALTH:
            if entry.reconnect_status == "blocked":
                health = ConnectorHealth.DEGRADED
            elif entry.reconnect_status == "ready":
                health = ConnectorHealth.HEALTHY
            else:
                health = ConnectorHealth.UNKNOWN

        if health is not state.health:
            state = self._settings.update_health(
                connector_id,
                project_id=request.project_id,
                health=health,
            )

        return BuilderConnectorStatus(
            session_id=session_id,
            connector_id=connector_id,
            project_id=request.project_id,
            reconnect_status=entry.reconnect_status,
            connector_ready=state.ready,
            connector_health=state.health,
            settings_deep_link=f"settings://connectors/{connector_id}",
            resume_allowed=entry.reconnect_status == "ready" and state.ready,
        )

    def set_reconnect_status(
        self,
        session_id: str,
        status: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
        blocker: str | None = None,
    ) -> BuilderConnectorStatus:
        self._binding(session_id, request=request, current_epoch=current_epoch)
        self._startup.set_reconnect_status(
            session_id,
            status,
            request=request,
            current_epoch=current_epoch,
            blocker=blocker,
        )
        return self.sync(session_id, request=request, current_epoch=current_epoch)

    def resume_job(
        self,
        session_id: str,
        job_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> BuilderJobCheckpoint:
        """Resume recovered work only when provider and canonical Settings are Ready.

        This is the UI/control-surface resume path. It deliberately re-syncs immediately
        before mutation so an expired credential, disabled connector, provider migration,
        or reconnect regression cannot race a stale previously-ready snapshot.
        """
        status = self.sync(
            session_id,
            request=request,
            current_epoch=current_epoch,
        )
        if not status.resume_allowed:
            raise AuthorityError(
                "builder job resume requires provider reconnect and Ready Connector Settings"
            )
        checkpoint = self._startup.resume_job(
            session_id,
            job_id,
            request=request,
            current_epoch=current_epoch,
        )
        if checkpoint.session_id != session_id:
            raise AuthorityError("resumed builder job changed session ownership")
        return checkpoint
