from __future__ import annotations
from dataclasses import dataclass
from typing import FrozenSet
import re

_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_AUTH = {"oauth", "api-key", "local", "none"}
_HEALTH = {"unknown", "healthy", "degraded", "auth-required", "expired", "migration-required", "unavailable"}

class ConnectorStateError(ValueError):
    pass

@dataclass(frozen=True)
class ConnectorState:
    connector_id: str
    installed: bool
    connected: bool
    enabled: bool
    auth_method: str
    health: str
    permissions: FrozenSet[str]
    setup_version: int
    verified_setup_version: int | None = None

    @property
    def ready(self) -> bool:
        return (
            self.installed and self.enabled and
            (self.auth_method in {"none", "local"} or self.connected) and
            self.health == "healthy" and
            self.verified_setup_version == self.setup_version
        )

def validate_state(state: ConnectorState, known_permissions: set[str]) -> ConnectorState:
    if not _ID.fullmatch(state.connector_id):
        raise ConnectorStateError("invalid connector_id")
    if state.auth_method not in _AUTH or state.health not in _HEALTH:
        raise ConnectorStateError("unknown connector state value")
    if state.setup_version < 1:
        raise ConnectorStateError("invalid setup_version")
    if not state.permissions.issubset(known_permissions):
        raise ConnectorStateError("unknown permission")
    if state.connected and not state.installed:
        raise ConnectorStateError("connector cannot be connected before install")
    if state.enabled and not state.installed:
        raise ConnectorStateError("connector cannot be enabled before install")
    return state

def remediation_code(state: ConnectorState) -> str | None:
    if not state.installed:
        return "install"
    if state.auth_method in {"oauth", "api-key"} and not state.connected:
        return "connect"
    if state.health in {"expired", "auth-required"}:
        return "reconnect"
    if state.health == "migration-required" or state.verified_setup_version != state.setup_version:
        return "update-setup"
    if state.health in {"degraded", "unavailable"}:
        return "test-connection"
    if not state.enabled:
        return "enable"
    return None
