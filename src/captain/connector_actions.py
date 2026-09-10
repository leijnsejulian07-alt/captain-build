"""Safe execution boundary for Captain connector actions.

Provider adapters own OAuth/browser flows and credential-store interaction. Captain
keeps only lifecycle/health metadata and opaque credential handles; raw secrets never
enter registry state, action receipts, or persistent event checkpoints.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Mapping, Optional, Protocol, Tuple
from urllib.parse import urlparse

from .connector_settings import (
    AuthMethod,
    ConnectorError,
    ConnectorHealth,
    ConnectorSetupSpec,
    ConnectorSettingsRegistry,
)

_SENSITIVE_KEYS = ("secret", "token", "password", "api_key", "apikey", "credential", "authorization")
_ALLOWED_CREDENTIAL_SCHEMES = {"vault", "os-credential", "secretref"}


def _validate_safe_metadata(value: object, *, path: str = "metadata") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key).lower()
            if any(marker in name for marker in _SENSITIVE_KEYS):
                raise ConnectorError(f"sensitive field forbidden in {path}")
            _validate_safe_metadata(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_safe_metadata(item, path=f"{path}[{index}]")


def _validate_credential_handle(handle: str) -> None:
    parsed = urlparse(handle)
    if parsed.scheme not in _ALLOWED_CREDENTIAL_SCHEMES or not (parsed.netloc or parsed.path):
        raise ConnectorError("credential reference must use an approved credential-store scheme")
    if parsed.query or parsed.fragment or "@" in parsed.netloc:
        raise ConnectorError("credential reference may not embed query, fragment, or userinfo")


def _validate_permissions(permissions: Tuple[str, ...]) -> None:
    if len(set(permissions)) != len(permissions):
        raise ConnectorError("provider returned duplicate permissions")
    for permission in permissions:
        if not isinstance(permission, str) or not permission.strip() or permission != permission.strip():
            raise ConnectorError("provider permissions must be non-empty normalized strings")
        lowered = permission.lower()
        if any(marker in lowered for marker in _SENSITIVE_KEYS):
            raise ConnectorError("provider permission name appears to expose sensitive material")


@dataclass(frozen=True)
class ConnectResult:
    connected: bool
    auth_material_present: bool
    authorization_url: Optional[str] = None
    safe_metadata: Mapping[str, object] = None
    granted_permissions: Tuple[str, ...] = ()

    def validate(self, *, auth_method: AuthMethod) -> None:
        metadata = {} if self.safe_metadata is None else self.safe_metadata
        _validate_safe_metadata(metadata)
        _validate_permissions(self.granted_permissions)
        if self.connected and auth_method in {AuthMethod.OAUTH, AuthMethod.API_KEY, AuthMethod.ID_BASED} and not self.auth_material_present:
            raise ConnectorError("authenticated connection succeeded without auth material")
        if self.authorization_url is not None:
            parsed = urlparse(self.authorization_url)
            if auth_method is not AuthMethod.OAUTH:
                raise ConnectorError("authorization URL is OAuth-only")
            if parsed.scheme != "https" or not parsed.netloc:
                raise ConnectorError("OAuth authorization URL must use HTTPS")


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    health: ConnectorHealth
    safe_message: str
    provider_version: str = ""
    provider_auth_version: str = ""
    safe_metadata: Mapping[str, object] = None
    permissions_authoritative: bool = False
    granted_permissions: Tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_safe_metadata({} if self.safe_metadata is None else self.safe_metadata)
        if not isinstance(self.safe_message, str) or not self.safe_message.strip():
            raise ConnectorError("connection-test message must be non-empty")
        if any(marker in self.safe_message.lower() for marker in _SENSITIVE_KEYS):
            raise ConnectorError("connection-test message may expose sensitive material")
        _validate_permissions(self.granted_permissions)
        if self.granted_permissions and not self.permissions_authoritative:
            raise ConnectorError("test permissions require an authoritative provider observation")
        if not self.ok and self.health is ConnectorHealth.HEALTHY:
            raise ConnectorError("failed connection test cannot report healthy status")
        if self.ok and self.health is ConnectorHealth.AUTH_INVALID:
            raise ConnectorError("successful connection test cannot report invalid authentication")


class ConnectorProviderAdapter(Protocol):
    def connect(self, *, project_id: Optional[str], credential_handle: Optional[str]) -> ConnectResult: ...
    def test_connection(self, *, project_id: Optional[str]) -> ConnectionTestResult: ...


class ConnectorActionService:
    """Runs explicit connector actions without becoming an auth or routing daemon."""

    def __init__(self, registry: ConnectorSettingsRegistry) -> None:
        self._registry = registry
        self._setups: Dict[str, ConnectorSetupSpec] = {}
        self._adapters: Dict[str, ConnectorProviderAdapter] = {}

    def register(self, setup: ConnectorSetupSpec, adapter: ConnectorProviderAdapter) -> None:
        setup.validate()
        if setup.connector_id in self._setups:
            raise ConnectorError("connector adapter already registered")
        self._setups[setup.connector_id] = setup
        self._adapters[setup.connector_id] = adapter

    def registered_connector_ids(self) -> Tuple[str, ...]:
        """Return the immutable public connector catalog without adapter internals."""
        return tuple(sorted(self._setups))

    def setup_for(self, connector_id: str) -> ConnectorSetupSpec:
        """Expose only non-secret setup metadata needed by Captain Settings."""
        setup = self._setups.get(connector_id)
        if setup is None:
            raise ConnectorError("connector adapter is not registered")
        return setup

    def _parts(self, connector_id: str, project_id: Optional[str]) -> Tuple[ConnectorSetupSpec, ConnectorProviderAdapter]:
        setup, adapter = self._setups.get(connector_id), self._adapters.get(connector_id)
        if setup is None or adapter is None:
            raise ConnectorError("connector adapter is not registered")
        state = self._registry.get(connector_id, project_id=project_id)
        if state is None or not state.installed:
            raise ConnectorError("connector must be installed before actions can run")
        if state.auth_method is not setup.auth_method:
            raise ConnectorError("connector auth-method mismatch")
        return setup, adapter

    def connect(self, connector_id: str, *, project_id: Optional[str], credential_handle: Optional[str] = None, user_initiated: bool) -> ConnectResult:
        if not user_initiated:
            raise ConnectorError("connect requires explicit user action")
        setup, adapter = self._parts(connector_id, project_id)
        if setup.auth_method is AuthMethod.OAUTH and credential_handle is not None:
            raise ConnectorError("OAuth must use the official provider flow")
        if setup.auth_method in {AuthMethod.API_KEY, AuthMethod.ID_BASED}:
            if not credential_handle:
                raise ConnectorError("credential-store handle is required")
            _validate_credential_handle(credential_handle)
        result = adapter.connect(project_id=project_id, credential_handle=credential_handle)
        result.validate(auth_method=setup.auth_method)
        if result.connected:
            current = self._registry.get(connector_id, project_id=project_id)
            assert current is not None
            self._registry.put(
                replace(
                    current,
                    connected=True,
                    auth_material_present=result.auth_material_present,
                    permissions=frozenset(result.granted_permissions),
                )
            )
        return result

    def test_connection(self, connector_id: str, *, project_id: Optional[str], user_initiated: bool) -> ConnectionTestResult:
        if not user_initiated:
            raise ConnectorError("test connection requires explicit user action")
        setup, adapter = self._parts(connector_id, project_id)
        if not setup.test_connection_supported:
            raise ConnectorError("connector does not support Test Connection")
        result = adapter.test_connection(project_id=project_id)
        result.validate()
        current = self._registry.get(connector_id, project_id=project_id)
        assert current is not None
        permissions = (
            frozenset(result.granted_permissions)
            if result.permissions_authoritative
            else current.permissions
        )
        self._registry.put(
            replace(
                current,
                health=result.health,
                version=result.provider_version or current.version,
                provider_auth_version=result.provider_auth_version or current.provider_auth_version,
                permissions=permissions,
            )
        )
        return result