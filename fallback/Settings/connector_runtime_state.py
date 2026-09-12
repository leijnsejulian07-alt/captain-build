from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet


class AuthMethod(str, Enum):
    NONE = "none"
    OAUTH = "oauth"
    API_KEY = "api_key"
    ID = "id"


@dataclass(frozen=True)
class ConnectorRuntimeState:
    connector_id: str
    installed: bool
    connected: bool
    enabled: bool
    ready: bool
    auth_method: AuthMethod
    permissions: FrozenSet[str] = frozenset()
    health: str = "unknown"
    remediation_code: str | None = None

    def validate(self) -> "ConnectorRuntimeState":
        if not self.connector_id or any(c.isspace() for c in self.connector_id):
            raise ValueError("invalid connector_id")
        if self.connected and not self.installed:
            raise ValueError("connected connector must be installed")
        if self.enabled and not self.installed:
            raise ValueError("enabled connector must be installed")
        if self.ready and not (self.installed and self.connected and self.enabled):
            raise ValueError("ready requires installed + connected + enabled")
        if self.auth_method != AuthMethod.NONE and self.connected is False:
            # Auth may be configured only through an explicit connect/test flow.
            if self.ready:
                raise ValueError("authenticated connector cannot be ready while disconnected")
        if self.health == "healthy" and not self.ready:
            raise ValueError("healthy connector must be ready")
        if self.health in {"invalid_credentials", "expired", "deprecated_auth", "migration_required"} and not self.remediation_code:
            raise ValueError("unhealthy connector requires remediation_code")
        return self

    @property
    def may_execute(self) -> bool:
        """Single fail-closed gate used by Captain before invoking a connector."""
        return bool(
            self.installed
            and self.connected
            and self.enabled
            and self.ready
            and self.health == "healthy"
        )

    def public_status(self) -> dict[str, object]:
        """UI-safe status only; never carries credentials, tokens, IDs, or secret material."""
        return {
            "connector_id": self.connector_id,
            "installed": self.installed,
            "connected": self.connected,
            "enabled": self.enabled,
            "ready": self.ready,
            "auth_method": self.auth_method.value,
            "permissions": sorted(self.permissions),
            "health": self.health,
            "remediation_code": self.remediation_code,
        }
