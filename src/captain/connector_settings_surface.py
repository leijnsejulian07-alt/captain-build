"""Secret-free presentation model for Captain's canonical connector Settings UI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .connector_actions import ConnectorActionService
from .connector_settings import AuthMethod, ConnectorError, ConnectorSettingsRegistry, ConnectorState


@dataclass(frozen=True)
class ConnectorSettingsRow:
    connector_id: str
    project_id: Optional[str]
    installed: bool
    connected: bool
    enabled: bool
    ready: bool
    auth_method: str
    permissions: Tuple[str, ...]
    required_permissions: Tuple[str, ...]
    health: str
    version: str
    provider_auth_version: str
    paid_service: bool
    setup_mode: str
    required_fields: Tuple[str, ...]
    actions: Tuple[str, ...]
    remediation: Optional[dict]
    settings_deep_link: str

    def safe_payload(self) -> dict:
        return {
            "connector_id": self.connector_id,
            "project_id": self.project_id,
            "installed": self.installed,
            "connected": self.connected,
            "enabled": self.enabled,
            "ready": self.ready,
            "auth_method": self.auth_method,
            "permissions": list(self.permissions),
            "required_permissions": list(self.required_permissions),
            "health": self.health,
            "version": self.version,
            "provider_auth_version": self.provider_auth_version,
            "paid_service": self.paid_service,
            "setup_mode": self.setup_mode,
            "required_fields": list(self.required_fields),
            "actions": list(self.actions),
            "remediation": self.remediation,
            "settings_deep_link": self.settings_deep_link,
        }


class ConnectorSettingsSurface:
    """Build the only connector view-model consumed by Settings/Control Center."""

    def __init__(self, registry: ConnectorSettingsRegistry, actions: ConnectorActionService) -> None:
        self._registry = registry
        self._actions = actions

    @staticmethod
    def _scope_key(project_id: Optional[str], connector_id: str) -> Tuple[Optional[str], str]:
        return project_id, connector_id

    def rows(self, *, project_id: Optional[str], now: float) -> Tuple[ConnectorSettingsRow, ...]:
        notices: Dict[Tuple[Optional[str], str], dict] = {
            self._scope_key(n.project_id, n.connector_id): n.safe_payload()
            for n in self._registry.visible_notices(project_id=project_id, now=now)
        }
        result = []
        for connector_id in self._actions.registered_connector_ids():
            scopes = (None,) if project_id is None else (None, project_id)
            for scope in scopes:
                state = self._registry.get(connector_id, project_id=scope)
                if state is None:
                    continue
                result.append(self._row(state, notices.get(self._scope_key(scope, connector_id))))
        return tuple(sorted(result, key=lambda row: (row.connector_id, row.project_id or "")))

    def _row(self, state: ConnectorState, remediation: Optional[dict]) -> ConnectorSettingsRow:
        setup = self._actions.setup_for(state.connector_id)
        if state.auth_method is not setup.auth_method:
            raise ConnectorError("Settings surface detected connector auth-method drift")
        actions = []
        if state.installed and not state.connected:
            actions.append("connect")
        if state.installed and state.connected and setup.test_connection_supported:
            actions.append("test_connection")
        if state.installed and not state.enabled:
            actions.append("enable_with_approval" if state.paid_service else "enable")
        if state.enabled:
            actions.append("disable")
        if state.connected and not state.required_permissions.issubset(state.permissions):
            actions.append("review_permissions")
        if remediation is not None:
            actions.append("open_remediation")
        setup_mode = "official_oauth" if setup.auth_method is AuthMethod.OAUTH else "credential_store"
        if setup.auth_method is AuthMethod.LOCAL:
            setup_mode = "local"
        return ConnectorSettingsRow(
            connector_id=state.connector_id,
            project_id=state.project_id,
            installed=state.installed,
            connected=state.connected,
            enabled=state.enabled,
            ready=state.ready,
            auth_method=state.auth_method.value,
            permissions=tuple(sorted(state.permissions)),
            required_permissions=tuple(sorted(state.required_permissions)),
            health=state.health.value,
            version=state.version,
            provider_auth_version=state.provider_auth_version,
            paid_service=state.paid_service,
            setup_mode=setup_mode,
            required_fields=setup.required_fields,
            actions=tuple(actions),
            remediation=remediation,
            settings_deep_link=f"settings://connectors/{state.connector_id}",
        )
