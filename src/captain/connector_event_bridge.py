"""Secret-free connector health/remediation event bridge for Captain UI surfaces.

The bridge converts canonical ConnectorSettingsRegistry state into scoped UI events.
It never owns credentials, performs auth, or activates providers.  Global connector
notices may be shown in any project; project-scoped notices never cross project walls.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

from .connector_settings import ConnectorError, ConnectorSettingsRegistry


class ConnectorEventKind(str, Enum):
    STATUS_CHANGED = "status_changed"
    REMEDIATION_OPENED = "remediation_opened"
    REMEDIATION_CLEARED = "remediation_cleared"


@dataclass(frozen=True)
class ConnectorUiEvent:
    sequence: int
    connector_id: str
    project_id: Optional[str]
    kind: ConnectorEventKind
    payload: dict

    def visible_in(self, *, project_id: Optional[str]) -> bool:
        return self.project_id is None or self.project_id == project_id


class ConnectorEventBridge:
    """Produce monotonic, scoped UI events from the canonical connector registry."""

    def __init__(self, registry: ConnectorSettingsRegistry) -> None:
        self._registry = registry
        self._sequence = 0
        self._last_status: Dict[Tuple[Optional[str], str], dict] = {}
        self._notice_open: Dict[Tuple[Optional[str], str], bool] = {}
        self._events: list[ConnectorUiEvent] = []

    @staticmethod
    def _key(connector_id: str, project_id: Optional[str]) -> Tuple[Optional[str], str]:
        if not connector_id.strip():
            raise ConnectorError("connector_id must be non-empty")
        if project_id is not None and not project_id.strip():
            raise ConnectorError("project_id must be non-empty when scoped")
        return project_id, connector_id

    def _emit(
        self,
        *,
        connector_id: str,
        project_id: Optional[str],
        kind: ConnectorEventKind,
        payload: dict,
    ) -> ConnectorUiEvent:
        self._sequence += 1
        event = ConnectorUiEvent(
            sequence=self._sequence,
            connector_id=connector_id,
            project_id=project_id,
            kind=kind,
            payload=dict(payload),
        )
        self._events.append(event)
        return event

    def reconcile(
        self,
        connector_id: str,
        *,
        project_id: Optional[str],
        now: float,
    ) -> Tuple[ConnectorUiEvent, ...]:
        """Reconcile one connector and emit only meaningful UI changes."""
        key = self._key(connector_id, project_id)
        state = self._registry.get(connector_id, project_id=project_id)
        if state is None:
            raise ConnectorError("unknown connector")

        before = len(self._events)
        safe_status = state.safe_status()
        previous_status = self._last_status.get(key)
        if previous_status != safe_status:
            self._last_status[key] = dict(safe_status)
            self._emit(
                connector_id=connector_id,
                project_id=project_id,
                kind=ConnectorEventKind.STATUS_CHANGED,
                payload=safe_status,
            )

        visible_notice = next(
            (
                notice
                for notice in self._registry.visible_notices(project_id=project_id, now=now)
                if notice.connector_id == connector_id and notice.project_id == project_id
            ),
            None,
        )
        is_open = visible_notice is not None
        was_open = self._notice_open.get(key, False)

        if is_open and not was_open:
            self._emit(
                connector_id=connector_id,
                project_id=project_id,
                kind=ConnectorEventKind.REMEDIATION_OPENED,
                payload=visible_notice.safe_payload(),
            )
        elif was_open and not is_open:
            self._emit(
                connector_id=connector_id,
                project_id=project_id,
                kind=ConnectorEventKind.REMEDIATION_CLEARED,
                payload={
                    "connector_id": connector_id,
                    "project_id": project_id,
                },
            )
        self._notice_open[key] = is_open
        return tuple(self._events[before:])

    def startup_banners(
        self,
        *,
        project_id: Optional[str],
        now: float,
    ) -> Tuple[dict, ...]:
        """Return current unresolved safe notices suitable for app-launch banners."""
        notices = self._registry.visible_notices(project_id=project_id, now=now)
        return tuple(notice.safe_payload() for notice in notices)

    def events_since(
        self,
        sequence: int,
        *,
        project_id: Optional[str],
    ) -> Tuple[ConnectorUiEvent, ...]:
        """Read events after a cursor without leaking project-scoped connector events."""
        if sequence < 0:
            raise ConnectorError("sequence must be non-negative")
        return tuple(
            event
            for event in self._events
            if event.sequence > sequence and event.visible_in(project_id=project_id)
        )

    def checkpoint(self) -> dict:
        """Export secret-free replay state; safe for Captain-owned persistence."""
        return {
            "sequence": self._sequence,
            "last_status": [
                {
                    "project_id": project_id,
                    "connector_id": connector_id,
                    "status": dict(status),
                }
                for (project_id, connector_id), status in self._last_status.items()
            ],
            "notice_open": [
                {
                    "project_id": project_id,
                    "connector_id": connector_id,
                    "open": is_open,
                }
                for (project_id, connector_id), is_open in self._notice_open.items()
            ],
        }
