"""Connector/settings state-machine acceptance contract.

Fallback contract only. It specifies Captain's canonical Settings behavior for
connector lifecycle, health, permissions, auth and persistent remediation notices
without storing or exposing secrets.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, Optional


class AuthMethod(str, Enum):
    OAUTH = "oauth"
    API_KEY = "api_key"
    ID_BASED = "id_based"
    LOCAL = "local"


class Health(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    AUTH_INVALID = "auth_invalid"
    DEPRECATED = "deprecated"
    MIGRATION_REQUIRED = "migration_required"


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
    health: Health = Health.UNKNOWN
    version: str = ""
    auth_material_present: bool = False
    paid_service: bool = False
    paid_activation_approved: bool = False

    def validate(self) -> None:
        if not self.connector_id.strip():
            raise ValueError("connector_id must be non-empty")
        if self.connected and not self.installed:
            raise ValueError("connected connector must be installed")
        if self.enabled and not self.installed:
            raise ValueError("enabled connector must be installed")
        if self.connected and self.auth_method in {AuthMethod.OAUTH, AuthMethod.API_KEY, AuthMethod.ID_BASED}:
            if not self.auth_material_present:
                raise ValueError("connected authenticated connector requires auth material")
        if self.paid_service and self.enabled and not self.paid_activation_approved:
            raise ValueError("paid connector cannot be enabled without explicit approval")

    @property
    def ready(self) -> bool:
        try:
            self.validate()
        except ValueError:
            return False
        if not (self.installed and self.connected and self.enabled):
            return False
        if not self.required_permissions.issubset(self.permissions):
            return False
        if self.health is not Health.HEALTHY:
            return False
        return True


@dataclass(frozen=True)
class ConnectorNotice:
    connector_id: str
    project_id: Optional[str]
    reason: str
    settings_deep_link: str

    def safe_payload(self) -> dict:
        return {
            "connector_id": self.connector_id,
            "project_id": self.project_id,
            "reason": self.reason,
            "settings_deep_link": self.settings_deep_link,
        }


def needs_notice(state: ConnectorState) -> bool:
    try:
        state.validate()
    except ValueError:
        return True
    if not state.installed:
        return False
    if state.enabled and not state.connected:
        return True
    if state.health in {
        Health.AUTH_INVALID,
        Health.DEPRECATED,
        Health.MIGRATION_REQUIRED,
        Health.DEGRADED,
    }:
        return True
    if state.connected and not state.required_permissions.issubset(state.permissions):
        return True
    return False


def visible_to_project(notice: ConnectorNotice, project_id: Optional[str]) -> bool:
    return notice.project_id is None or notice.project_id == project_id


def main() -> None:
    healthy = ConnectorState(
        connector_id="github",
        project_id=None,
        installed=True,
        connected=True,
        enabled=True,
        auth_method=AuthMethod.OAUTH,
        permissions=frozenset({"repo:read", "repo:write"}),
        required_permissions=frozenset({"repo:read"}),
        health=Health.HEALTHY,
        version="1.2.3",
        auth_material_present=True,
    )
    assert healthy.ready
    assert not needs_notice(healthy)

    # Installed / Connected / Enabled / Ready are distinct states.
    assert not ConnectorState(
        "github", None, True, False, False, AuthMethod.OAUTH
    ).ready
    assert not ConnectorState(
        "github", None, True, True, False, AuthMethod.OAUTH,
        auth_material_present=True, health=Health.HEALTHY
    ).ready
    assert not ConnectorState(
        "github", None, True, True, True, AuthMethod.OAUTH,
        required_permissions=frozenset({"repo:write"}),
        permissions=frozenset({"repo:read"}),
        auth_material_present=True, health=Health.HEALTHY
    ).ready

    # Invalid/expired auth and provider migrations stay visibly unresolved.
    for health in (Health.AUTH_INVALID, Health.DEPRECATED, Health.MIGRATION_REQUIRED):
        state = ConnectorState(
            "provider", None, True, True, True, AuthMethod.OAUTH,
            auth_material_present=True, health=health
        )
        assert not state.ready
        assert needs_notice(state)

    # Never auto-enable paid services without explicit approval.
    paid = ConnectorState(
        "paid-provider", None, True, True, True, AuthMethod.API_KEY,
        auth_material_present=True, health=Health.HEALTHY,
        paid_service=True, paid_activation_approved=False
    )
    assert not paid.ready
    assert needs_notice(paid)

    # Safe notification payload contains only remediation metadata.
    notice = ConnectorNotice(
        connector_id="github",
        project_id="project-a",
        reason="Authentication expired",
        settings_deep_link="settings://connectors/github",
    )
    payload = notice.safe_payload()
    assert set(payload) == {"connector_id", "project_id", "reason", "settings_deep_link"}

    # Scoped notices cannot leak across projects.
    assert visible_to_project(notice, "project-a")
    assert not visible_to_project(notice, "project-b")
    global_notice = ConnectorNotice("github", None, "Update available", "settings://connectors/github")
    assert visible_to_project(global_notice, "project-a")
    assert visible_to_project(global_notice, None)


if __name__ == "__main__":
    main()
