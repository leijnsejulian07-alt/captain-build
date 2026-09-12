from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

from connector_runtime_state import ConnectorRuntimeState


_UNHEALTHY = {"invalid_credentials", "expired", "deprecated_auth", "migration_required"}
_MAX_CODE_LEN = 96


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _safe_code(value: str, field: str) -> str:
    if not value or len(value) > _MAX_CODE_LEN:
        raise ValueError(f"invalid {field}")
    if any(ch.isspace() for ch in value):
        raise ValueError(f"invalid {field}")
    lowered = value.lower()
    if any(marker in lowered for marker in ("token=", "api_key=", "apikey=", "secret=", "password=")):
        raise ValueError(f"secret-like material forbidden in {field}")
    return value


@dataclass
class ConnectorNotice:
    scope_id: str
    connector_id: str
    remediation_code: str
    first_seen_at: datetime
    last_seen_at: datetime
    dismissed_until: datetime | None = None

    @property
    def deep_link(self) -> str:
        return f"captain://settings/connectors/{self.connector_id}"

    def visible_at(self, now: datetime) -> bool:
        now = _utc(now)
        return self.dismissed_until is None or now >= self.dismissed_until

    def public_status(self, now: datetime) -> dict[str, object]:
        """UI-safe notice projection. No credentials, provider payloads, or raw errors."""
        return {
            "scope_id": self.scope_id,
            "connector_id": self.connector_id,
            "remediation_code": self.remediation_code,
            "deep_link": self.deep_link,
            "visible": self.visible_at(now),
        }

    def persisted_record(self) -> dict[str, object]:
        """Minimal persistence payload suitable for app relaunches."""
        payload = asdict(self)
        for key in ("first_seen_at", "last_seen_at", "dismissed_until"):
            value = payload[key]
            payload[key] = value.isoformat() if value is not None else None
        return payload


class ConnectorNoticeStore:
    """Fail-closed connector remediation notices scoped to one Captain settings authority.

    The store only persists stable identifiers, remediation codes, and timestamps. Provider
    error bodies, credentials, account IDs, and tokens are intentionally not accepted.
    """

    def __init__(self, *, scope_id: str, reminder_interval: timedelta = timedelta(hours=24)) -> None:
        self.scope_id = _safe_code(scope_id, "scope_id")
        if reminder_interval <= timedelta(0):
            raise ValueError("reminder_interval must be positive")
        self.reminder_interval = reminder_interval
        self._notices: dict[str, ConnectorNotice] = {}

    def reconcile(self, states: Iterable[ConnectorRuntimeState], *, now: datetime) -> None:
        """Create/update unresolved notices and auto-clear connectors that are healthy again."""
        now = _utc(now)
        seen: set[str] = set()
        for state in states:
            state.validate()
            connector_id = _safe_code(state.connector_id, "connector_id")
            seen.add(connector_id)
            needs_notice = state.health in _UNHEALTHY or bool(state.remediation_code and not state.may_execute)
            if not needs_notice:
                self._notices.pop(connector_id, None)
                continue
            code = _safe_code(state.remediation_code or f"connector_{state.health}", "remediation_code")
            current = self._notices.get(connector_id)
            if current is None or current.remediation_code != code:
                self._notices[connector_id] = ConnectorNotice(
                    scope_id=self.scope_id,
                    connector_id=connector_id,
                    remediation_code=code,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            else:
                current.last_seen_at = now

        # Do not clear notices for connectors omitted from a partial health poll. This keeps
        # unresolved setup problems persistent until Captain positively observes resolution.

    def dismiss_temporarily(self, connector_id: str, *, now: datetime) -> None:
        connector_id = _safe_code(connector_id, "connector_id")
        notice = self._notices.get(connector_id)
        if notice is None:
            raise KeyError(connector_id)
        notice.dismissed_until = _utc(now) + self.reminder_interval

    def visible(self, *, now: datetime) -> list[dict[str, object]]:
        now = _utc(now)
        return [
            notice.public_status(now)
            for notice in sorted(self._notices.values(), key=lambda item: item.connector_id)
            if notice.visible_at(now)
        ]

    def persisted_records(self) -> list[dict[str, object]]:
        return [notice.persisted_record() for notice in sorted(self._notices.values(), key=lambda item: item.connector_id)]

    @classmethod
    def from_persisted_records(
        cls,
        *,
        scope_id: str,
        records: Iterable[dict[str, object]],
        reminder_interval: timedelta = timedelta(hours=24),
    ) -> "ConnectorNoticeStore":
        store = cls(scope_id=scope_id, reminder_interval=reminder_interval)
        for raw in records:
            if raw.get("scope_id") != store.scope_id:
                raise ValueError("cross-scope connector notice rejected")
            connector_id = _safe_code(str(raw.get("connector_id", "")), "connector_id")
            code = _safe_code(str(raw.get("remediation_code", "")), "remediation_code")
            first_seen = _utc(datetime.fromisoformat(str(raw["first_seen_at"])))
            last_seen = _utc(datetime.fromisoformat(str(raw["last_seen_at"])))
            dismissed_raw = raw.get("dismissed_until")
            dismissed = _utc(datetime.fromisoformat(str(dismissed_raw))) if dismissed_raw else None
            store._notices[connector_id] = ConnectorNotice(
                scope_id=store.scope_id,
                connector_id=connector_id,
                remediation_code=code,
                first_seen_at=first_seen,
                last_seen_at=last_seen,
                dismissed_until=dismissed,
            )
        return store
