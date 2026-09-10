"""Canonical connector Settings/Control Center coordinator.

This module is intentionally a thin control surface over Captain's existing connector
registry, action service, settings view-model and remediation event bridge. It does not
own credentials, perform provider routing, or create a second daemon/control-plane.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .connector_actions import ConnectResult, ConnectionTestResult, ConnectorActionService
from .connector_event_bridge import ConnectorEventBridge, ConnectorUiEvent
from .connector_settings import ConnectorError, ConnectorSettingsRegistry
from .connector_settings_surface import ConnectorSettingsRow, ConnectorSettingsSurface


@dataclass(frozen=True)
class ConnectorControlCenterSnapshot:
    """Secret-free state consumed by Captain Settings and launch banners."""

    rows: Tuple[ConnectorSettingsRow, ...]
    banners: Tuple[dict, ...]
    event_cursor: int

    def safe_payload(self) -> dict:
        return {
            "rows": [row.safe_payload() for row in self.rows],
            "banners": [dict(item) for item in self.banners],
            "event_cursor": self.event_cursor,
        }


@dataclass(frozen=True)
class ConnectorControlCenterResult:
    snapshot: ConnectorControlCenterSnapshot
    events: Tuple[ConnectorUiEvent, ...]
    connect_result: Optional[ConnectResult] = None
    test_result: Optional[ConnectionTestResult] = None


class ConnectorControlCenter:
    """Single UI-facing coordinator for connector lifecycle actions.

    Provider adapters remain behind ConnectorActionService. Raw authentication material
    must never be returned through snapshots/events. Mutating actions always require
    explicit user intent; paid activation additionally requires explicit approval.
    """

    _MUTATING_ACTIONS = {
        "connect",
        "test_connection",
        "enable",
        "enable_with_approval",
        "disable",
        "dismiss_remediation",
    }

    def __init__(
        self,
        registry: ConnectorSettingsRegistry,
        actions: ConnectorActionService,
        bridge: ConnectorEventBridge,
    ) -> None:
        self._registry = registry
        self._actions = actions
        self._bridge = bridge
        self._surface = ConnectorSettingsSurface(registry, actions)

    def _scopes(self, *, connector_id: str, project_id: Optional[str]) -> Tuple[Optional[str], ...]:
        scopes = []
        if self._registry.get(connector_id, project_id=None) is not None:
            scopes.append(None)
        if project_id is not None and self._registry.get(connector_id, project_id=project_id) is not None:
            scopes.append(project_id)
        return tuple(scopes)

    def _reconcile_visible(self, *, project_id: Optional[str], now: float) -> None:
        for connector_id in self._actions.registered_connector_ids():
            for scope in self._scopes(connector_id=connector_id, project_id=project_id):
                self._bridge.reconcile(connector_id, project_id=scope, now=now)

    def snapshot(self, *, project_id: Optional[str], now: float) -> ConnectorControlCenterSnapshot:
        self._reconcile_visible(project_id=project_id, now=now)
        checkpoint = self._bridge.checkpoint()
        return ConnectorControlCenterSnapshot(
            rows=self._surface.rows(project_id=project_id, now=now),
            banners=self._bridge.startup_banners(project_id=project_id, now=now),
            event_cursor=checkpoint["sequence"],
        )

    def perform(
        self,
        connector_id: str,
        action: str,
        *,
        project_id: Optional[str],
        now: float,
        user_initiated: bool,
        credential_handle: Optional[str] = None,
        dismiss_until: Optional[float] = None,
        paid_activation_approved: bool = False,
    ) -> ConnectorControlCenterResult:
        if action not in self._MUTATING_ACTIONS:
            raise ConnectorError("unknown or non-executable connector UI action")
        if not user_initiated:
            raise ConnectorError("connector Settings actions require explicit user action")

        before = self._bridge.checkpoint()["sequence"]
        connect_result: Optional[ConnectResult] = None
        test_result: Optional[ConnectionTestResult] = None

        if action == "connect":
            connect_result = self._actions.connect(
                connector_id,
                project_id=project_id,
                credential_handle=credential_handle,
                user_initiated=True,
            )
        elif action == "test_connection":
            test_result = self._actions.test_connection(
                connector_id,
                project_id=project_id,
                user_initiated=True,
            )
        elif action == "enable":
            state = self._registry.get(connector_id, project_id=project_id)
            if state is None:
                raise ConnectorError("unknown connector")
            if state.paid_service:
                raise ConnectorError("paid connector requires enable_with_approval")
            self._registry.set_enabled(connector_id, project_id=project_id, enabled=True)
        elif action == "enable_with_approval":
            state = self._registry.get(connector_id, project_id=project_id)
            if state is None:
                raise ConnectorError("unknown connector")
            if not state.paid_service:
                raise ConnectorError("approval action is reserved for paid connectors")
            if not paid_activation_approved:
                raise ConnectorError("paid connector activation requires explicit approval")
            self._registry.set_enabled(
                connector_id,
                project_id=project_id,
                enabled=True,
                paid_activation_approved=True,
            )
        elif action == "disable":
            self._registry.set_enabled(connector_id, project_id=project_id, enabled=False)
        elif action == "dismiss_remediation":
            if dismiss_until is None or dismiss_until <= now:
                raise ConnectorError("dismissal must have a future reminder time")
            self._registry.dismiss_notice(
                connector_id,
                project_id=project_id,
                until=dismiss_until,
            )

        self._reconcile_visible(project_id=project_id, now=now)
        snapshot = ConnectorControlCenterSnapshot(
            rows=self._surface.rows(project_id=project_id, now=now),
            banners=self._bridge.startup_banners(project_id=project_id, now=now),
            event_cursor=self._bridge.checkpoint()["sequence"],
        )
        return ConnectorControlCenterResult(
            snapshot=snapshot,
            events=self._bridge.events_since(before, project_id=project_id),
            connect_result=connect_result,
            test_result=test_result,
        )
