from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence


SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CAP_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,95}$")
_ALLOWED_AUTH = {"none", "oauth", "api_key", "id_based", "local"}
_ALLOWED_SCOPE = {"global", "project"}
_SECRET_KEYS = {
    "secret", "token", "password", "api_key", "apikey", "access_token",
    "refresh_token", "client_secret", "credential", "credentials",
}


class PluginSettingsError(ValueError):
    pass


def _safe_id(name: str, value: object) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise PluginSettingsError(f"invalid {name}")
    return value


def _capabilities(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PluginSettingsError("invalid capabilities")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _CAP_RE.fullmatch(item):
            raise PluginSettingsError("invalid capability")
        result.append(item)
    if len(result) > 64 or len(set(result)) != len(result):
        raise PluginSettingsError("invalid capabilities")
    return tuple(sorted(result))


def _permissions(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PluginSettingsError("invalid permissions")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _CAP_RE.fullmatch(item):
            raise PluginSettingsError("invalid permission")
        result.append(item)
    if len(result) > 64 or len(set(result)) != len(result):
        raise PluginSettingsError("invalid permissions")
    return tuple(sorted(result))


def _reject_secret_fields(record: Mapping[str, object]) -> None:
    for key in record:
        lowered = str(key).lower()
        if lowered in _SECRET_KEYS or any(part in lowered for part in ("secret", "token", "password")):
            raise PluginSettingsError("secret-bearing plugin metadata is forbidden")


@dataclass(frozen=True)
class PluginState:
    plugin_id: str
    installed: bool
    connected: bool
    enabled: bool
    ready: bool
    auth_method: str
    scope: str
    project_id: str | None
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...]
    health: str

    def dispatch_allowed(self, *, project_id: str | None, capability: str) -> bool:
        if not _CAP_RE.fullmatch(capability):
            raise PluginSettingsError("invalid requested capability")
        if not (self.installed and self.connected and self.enabled and self.ready):
            return False
        if capability not in self.capabilities:
            return False
        if self.scope == "project":
            if project_id is None or project_id != self.project_id:
                return False
        return True


def parse_plugin_state(record: Mapping[str, object]) -> PluginState:
    if not isinstance(record, Mapping):
        raise PluginSettingsError("invalid plugin record")
    _reject_secret_fields(record)
    required = {
        "schema_version", "plugin_id", "installed", "connected", "enabled", "ready",
        "auth_method", "scope", "project_id", "capabilities", "permissions", "health",
    }
    if set(record) != required or record.get("schema_version") != SCHEMA_VERSION:
        raise PluginSettingsError("invalid plugin record schema")

    plugin_id = _safe_id("plugin_id", record.get("plugin_id"))
    installed = record.get("installed")
    connected = record.get("connected")
    enabled = record.get("enabled")
    ready = record.get("ready")
    if not all(isinstance(value, bool) for value in (installed, connected, enabled, ready)):
        raise PluginSettingsError("plugin state flags must be bool")

    auth_method = record.get("auth_method")
    if auth_method not in _ALLOWED_AUTH:
        raise PluginSettingsError("invalid auth_method")
    scope = record.get("scope")
    if scope not in _ALLOWED_SCOPE:
        raise PluginSettingsError("invalid plugin scope")
    project_id = record.get("project_id")
    if scope == "project":
        project_id = _safe_id("project_id", project_id)
    elif project_id is not None:
        raise PluginSettingsError("global plugin cannot carry project_id")

    capabilities = _capabilities(record.get("capabilities"))
    permissions = _permissions(record.get("permissions"))
    health = record.get("health")
    if health not in {"healthy", "degraded", "blocked", "unknown"}:
        raise PluginSettingsError("invalid plugin health")

    if not installed and any((connected, enabled, ready)):
        raise PluginSettingsError("uninstalled plugin cannot be active")
    if connected and auth_method == "none" and scope != "global":
        raise PluginSettingsError("project plugin without auth cannot claim connected state")
    if enabled and not installed:
        raise PluginSettingsError("enabled plugin must be installed")
    if ready and not (installed and connected and enabled and health == "healthy"):
        raise PluginSettingsError("ready requires installed+connected+enabled+healthy")

    return PluginState(
        plugin_id=plugin_id,
        installed=installed,
        connected=connected,
        enabled=enabled,
        ready=ready,
        auth_method=auth_method,
        scope=scope,
        project_id=project_id,
        capabilities=capabilities,
        permissions=permissions,
        health=health,
    )


def build_plugin_settings_projection(
    records: Sequence[Mapping[str, object]], *, project_id: str | None = None
) -> dict[str, object]:
    active_project = _safe_id("project_id", project_id) if project_id is not None else None
    states = [parse_plugin_state(record) for record in records]
    ids = [state.plugin_id for state in states]
    if len(set(ids)) != len(ids):
        raise PluginSettingsError("duplicate plugin_id")

    visible: list[PluginState] = []
    for state in states:
        if state.scope == "global":
            visible.append(state)
        elif active_project is not None and state.project_id == active_project:
            visible.append(state)

    visible.sort(key=lambda state: state.plugin_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "plugins": [
            {
                "plugin_id": state.plugin_id,
                "installed": state.installed,
                "connected": state.connected,
                "enabled": state.enabled,
                "ready": state.ready,
                "auth_method": state.auth_method,
                "scope": state.scope,
                "capabilities": list(state.capabilities),
                "permissions": list(state.permissions),
                "health": state.health,
            }
            for state in visible
        ],
        "secret_fields": [],
    }


def authorize_plugin_dispatch(
    records: Sequence[Mapping[str, object]], *, plugin_id: str, capability: str, project_id: str | None = None
) -> dict[str, object]:
    target = _safe_id("plugin_id", plugin_id)
    states = [parse_plugin_state(record) for record in records]
    matches = [state for state in states if state.plugin_id == target]
    if len(matches) != 1:
        raise PluginSettingsError("plugin authority must resolve exactly once")
    state = matches[0]
    allowed = state.dispatch_allowed(project_id=project_id, capability=capability)
    return {
        "schema_version": SCHEMA_VERSION,
        "plugin_id": target,
        "capability": capability,
        "allowed": allowed,
        "reason": "ready" if allowed else "not_authorized",
        "secret_fields": [],
    }
