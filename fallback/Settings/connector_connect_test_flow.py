from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet

from connector_runtime_state import AuthMethod, ConnectorRuntimeState


class ConnectAction(str, Enum):
    NONE = "none"
    OFFICIAL_OAUTH = "official_oauth"
    ENTER_API_KEY = "enter_api_key"
    ENTER_ID = "enter_id"


_ALLOWED_HEALTH = {
    "healthy",
    "invalid_credentials",
    "expired",
    "deprecated_auth",
    "migration_required",
    "unreachable",
}


@dataclass(frozen=True)
class ConnectorSetupSpec:
    connector_id: str
    auth_method: AuthMethod
    required_fields: tuple[str, ...] = ()
    requested_permissions: FrozenSet[str] = frozenset()
    oauth_authorize_url: str | None = None

    def validate(self) -> "ConnectorSetupSpec":
        if not self.connector_id or any(ch.isspace() for ch in self.connector_id):
            raise ValueError("invalid connector_id")
        if self.auth_method == AuthMethod.OAUTH:
            if not self.oauth_authorize_url or not self.oauth_authorize_url.startswith("https://"):
                raise ValueError("oauth connectors require an official https authorize URL")
            if self.required_fields:
                raise ValueError("oauth connectors must not request manual secret fields")
        elif self.oauth_authorize_url is not None:
            raise ValueError("non-oauth connectors cannot define oauth_authorize_url")
        if self.auth_method == AuthMethod.API_KEY and self.required_fields != ("api_key",):
            raise ValueError("api-key connectors must explicitly request only api_key")
        if self.auth_method == AuthMethod.ID and not self.required_fields:
            raise ValueError("id connectors require explicit identifier field names")
        if self.auth_method == AuthMethod.NONE and (self.required_fields or self.oauth_authorize_url):
            raise ValueError("authless connector cannot request auth setup")
        for field in self.required_fields:
            if not field or any(ch.isspace() for ch in field):
                raise ValueError("invalid required field")
        return self

    @property
    def connect_action(self) -> ConnectAction:
        self.validate()
        return {
            AuthMethod.NONE: ConnectAction.NONE,
            AuthMethod.OAUTH: ConnectAction.OFFICIAL_OAUTH,
            AuthMethod.API_KEY: ConnectAction.ENTER_API_KEY,
            AuthMethod.ID: ConnectAction.ENTER_ID,
        }[self.auth_method]

    def public_setup(self) -> dict[str, object]:
        self.validate()
        return {
            "connector_id": self.connector_id,
            "auth_method": self.auth_method.value,
            "connect_action": self.connect_action.value,
            "required_fields": list(self.required_fields),
            "requested_permissions": sorted(self.requested_permissions),
            "oauth_authorize_url": self.oauth_authorize_url,
            "test_connection_available": True,
        }


@dataclass(frozen=True)
class ConnectionTestResult:
    connector_id: str
    ok: bool
    health: str
    granted_permissions: FrozenSet[str] = frozenset()
    remediation_code: str | None = None

    def validate(self) -> "ConnectionTestResult":
        if not self.connector_id or any(ch.isspace() for ch in self.connector_id):
            raise ValueError("invalid connector_id")
        if self.health not in _ALLOWED_HEALTH:
            raise ValueError("unsupported health result")
        if self.ok and self.health != "healthy":
            raise ValueError("successful test must be healthy")
        if not self.ok and self.health == "healthy":
            raise ValueError("failed test cannot be healthy")
        if self.ok and self.remediation_code is not None:
            raise ValueError("successful test cannot carry remediation")
        if not self.ok and self.health in {"invalid_credentials", "expired", "deprecated_auth", "migration_required"} and not self.remediation_code:
            raise ValueError("auth/setup failure requires remediation_code")
        if self.remediation_code:
            lowered = self.remediation_code.lower()
            if len(self.remediation_code) > 96 or any(ch.isspace() for ch in self.remediation_code):
                raise ValueError("invalid remediation_code")
            if any(marker in lowered for marker in ("token=", "api_key=", "apikey=", "secret=", "password=")):
                raise ValueError("secret-like remediation material forbidden")
        return self


def apply_test_result(
    *,
    current: ConnectorRuntimeState,
    spec: ConnectorSetupSpec,
    result: ConnectionTestResult,
    enabled: bool | None = None,
) -> ConnectorRuntimeState:
    """Convert an explicit Test Connection result into Captain runtime state.

    This function never invents credentials, never performs auth, and never enables a connector
    unless the caller explicitly requested that state. A successful test proves connection/health;
    it does not silently broaden permissions beyond what the provider reported.
    """
    current.validate()
    spec.validate()
    result.validate()
    if current.connector_id != spec.connector_id or current.connector_id != result.connector_id:
        raise ValueError("cross-connector setup/test result rejected")
    if current.auth_method != spec.auth_method:
        raise ValueError("auth method mismatch")

    next_enabled = current.enabled if enabled is None else bool(enabled)
    if result.ok:
        if not result.granted_permissions.issubset(spec.requested_permissions):
            raise ValueError("provider granted permissions outside requested set")
        next_state = ConnectorRuntimeState(
            connector_id=current.connector_id,
            installed=current.installed,
            connected=True,
            enabled=next_enabled,
            ready=bool(current.installed and next_enabled),
            auth_method=current.auth_method,
            permissions=result.granted_permissions,
            health="healthy" if current.installed and next_enabled else "unknown",
            remediation_code=None,
        )
    else:
        next_state = ConnectorRuntimeState(
            connector_id=current.connector_id,
            installed=current.installed,
            connected=False,
            enabled=next_enabled,
            ready=False,
            auth_method=current.auth_method,
            permissions=frozenset(),
            health=result.health,
            remediation_code=result.remediation_code,
        )
    return next_state.validate()
