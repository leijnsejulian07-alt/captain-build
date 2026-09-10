"""Canonical connector/settings runtime state for Captain.

The registry deliberately stores lifecycle metadata only. Secret/token material must
remain in the provider/OS credential store; Captain records only whether required
auth material is present and its non-sensitive health metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Dict, FrozenSet, Optional, Tuple


class ConnectorError(ValueError):
    pass


class AuthMethod(str, Enum):
    OAUTH = "oauth"
    API_KEY = "api_key"
    ID_BASED = "id_based"
    LOCAL = "local"


class ConnectorHealth(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    AUTH_INVALID = "auth_invalid"
    DEPRECATED = "deprecated"
    MIGRATION_REQUIRED = "migration_required"


@dataclass(frozen=True)
class ConnectorSetupSpec:
    connector_id: str
    auth_method: AuthMethod
    required_fields: Tuple[str, ...] = ()
    connect_label: str = "Connect"
    test_connection_supported: bool = True

    def validate(self) -> None:
        if not self.connector_id.strip():
            raise ConnectorError("connector_id must be non-empty")
        if self.auth_method is AuthMethod.OAUTH and self.required_fields:
            raise ConnectorError("OAuth setup must use the provider Connect flow, not manual secret fields")
        if any(not field.strip() for field in self.required_fields):
            raise ConnectorError("required field names must be non-empty")


@dataclass(frozen=True)
class ConnectorState:
    connector_id: str
    project_id: Optional[str]
    installed: bool
    connected: bool
    enabled: bool
    auth_method: AuthMethod
    permissions: FrozenSet[str] = field(default_factory=frozenset)
    required_permissions: FrozenSet[str] = field(default_factory=frozenset)
    health: ConnectorHealth = ConnectorHealth.UNKNOWN
    version: str = ""
    auth_material_present: bool = False
    paid_service: bool = False
    paid_activation_approved: bool = False
    provider_auth_version: str = ""

    def validate(self) -> None:
        if not self.connector_id.strip():
            raise ConnectorError("connector_id must be non-empty")
        if self.project_id is not None and not self.project_id.strip():
            raise ConnectorError("project_id must be non-empty when scoped")
        if self.connected and not self.installed:
            raise ConnectorError("connected connector must be installed")
        if self.enabled and not self.installed:
            raise ConnectorError("enabled connector must be installed")
        if self.connected and self.auth_method in {
            AuthMethod.OAUTH,
            AuthMethod.API_KEY,
            AuthMethod.ID_BASED,
        } and not self.auth_material_present:
            raise ConnectorError("connected authenticated connector requires auth material")
        if self.paid_service and self.enabled and not self.paid_activation_approved:
            raise ConnectorError("paid connector cannot be enabled without explicit approval")

    @property
    def ready(self) -> bool:
        try:
            self.validate()
        except ConnectorError:
            return False
        return (
            self.installed
            and self.connected
            and self.enabled
            and self.required_permissions.issubset(self.permissions)
            and self.health is ConnectorHealth.HEALTHY
        )

    def safe_status(self) -> dict:
        """Return UI/diagnostic metadata only; never credentials or secret values."""
        return {
            "connector_id": self.connector_id,
            "project_id": self.project_id,
            "installed": self.installed,
            "connected": self.connected,
            "enabled": self.enabled,
            "ready": self.ready,
            "permissions": sorted(self.permissions),
            "required_permissions": sorted(self.required_permissions),
            "health": self.health.value,
            "version": self.version,
            "auth_method": self.auth_method.value,
            "provider_auth_version": self.provider_auth_version,
            "paid_service": self.paid_service,
        }


@dataclass(frozen=True)
class ConnectorNotice:
    connector_id: str
    project_id: Optional[str]
    reason: str
    settings_deep_link: str
    dismissed_until: Optional[float] = None

    def visible(self, *, project_id: Optional[str], now: float) -> bool:
        if self.project_id is not None and self.project_id != project_id:
            return False
        return self.dismissed_until is None or now >= self.dismissed_until

    def safe_payload(self) -> dict:
        return {
            "connector_id": self.connector_id,
            "project_id": self.project_id,
            "reason": self.reason,
            "settings_deep_link": self.settings_deep_link,
        }


def remediation_reason(state: ConnectorState) -> Optional[str]:
    try:
        state.validate()
    except ConnectorError as exc:
        return str(exc)
    if not state.installed:
        return None
    if state.enabled and not state.connected:
        return "Connector is enabled but not connected"
    if state.health is ConnectorHealth.AUTH_INVALID:
        return "Authentication is invalid or expired"
    if state.health is ConnectorHealth.DEPRECATED:
        return "Provider version is deprecated"
    if state.health is ConnectorHealth.MIGRATION_REQUIRED:
        return "Provider authentication or setup migration is required"
    if state.health is ConnectorHealth.DEGRADED:
        return "Connector health is degraded"
    if state.connected and not state.required_permissions.issubset(state.permissions):
        return "Required permissions are missing"
    return None


class ConnectorSettingsRegistry:
    """Single runtime authority for connector lifecycle and remediation metadata."""

    def __init__(self) -> None:
        self._states: Dict[Tuple[Optional[str], str], ConnectorState] = {}
        self._notices: Dict[Tuple[Optional[str], str], ConnectorNotice] = {}

    @staticmethod
    def _key(connector_id: str, project_id: Optional[str]) -> Tuple[Optional[str], str]:
        if not connector_id.strip():
            raise ConnectorError("connector_id must be non-empty")
        if project_id is not None and not project_id.strip():
            raise ConnectorError("project_id must be non-empty when scoped")
        return project_id, connector_id

    def put(self, state: ConnectorState) -> ConnectorState:
        state.validate()
        key = self._key(state.connector_id, state.project_id)
        self._states[key] = state
        self._sync_notice(state)
        return state

    def get(self, connector_id: str, *, project_id: Optional[str]) -> Optional[ConnectorState]:
        return self._states.get(self._key(connector_id, project_id))

    def set_enabled(
        self,
        connector_id: str,
        *,
        project_id: Optional[str],
        enabled: bool,
        paid_activation_approved: bool = False,
    ) -> ConnectorState:
        key = self._key(connector_id, project_id)
        current = self._states.get(key)
        if current is None:
            raise ConnectorError("unknown connector")
        approval = current.paid_activation_approved or paid_activation_approved
        updated = replace(current, enabled=enabled, paid_activation_approved=approval)
        return self.put(updated)

    def update_health(
        self,
        connector_id: str,
        *,
        project_id: Optional[str],
        health: ConnectorHealth,
        version: Optional[str] = None,
        provider_auth_version: Optional[str] = None,
    ) -> ConnectorState:
        key = self._key(connector_id, project_id)
        current = self._states.get(key)
        if current is None:
            raise ConnectorError("unknown connector")
        updated = replace(
            current,
            health=health,
            version=current.version if version is None else version,
            provider_auth_version=(
                current.provider_auth_version
                if provider_auth_version is None
                else provider_auth_version
            ),
        )
        return self.put(updated)

    def dismiss_notice(
        self,
        connector_id: str,
        *,
        project_id: Optional[str],
        until: float,
    ) -> None:
        key = self._key(connector_id, project_id)
        notice = self._notices.get(key)
        if notice is None:
            raise ConnectorError("no unresolved notice")
        self._notices[key] = replace(notice, dismissed_until=until)

    def visible_notices(self, *, project_id: Optional[str], now: float) -> Tuple[ConnectorNotice, ...]:
        return tuple(
            notice
            for notice in self._notices.values()
            if notice.visible(project_id=project_id, now=now)
        )

    def _sync_notice(self, state: ConnectorState) -> None:
        key = self._key(state.connector_id, state.project_id)
        reason = remediation_reason(state)
        if reason is None:
            self._notices.pop(key, None)
            return
        existing = self._notices.get(key)
        self._notices[key] = ConnectorNotice(
            connector_id=state.connector_id,
            project_id=state.project_id,
            reason=reason,
            settings_deep_link=f"settings://connectors/{state.connector_id}",
            dismissed_until=existing.dismissed_until if existing else None,
        )
