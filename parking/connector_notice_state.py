"""Secret-free persistent remediation notice state for Captain Settings.

Consumes connector_health_monitor output only. It never receives credentials or
provider diagnostics. Important unresolved notices can be snoozed, but reappear
on a later launch or after the bounded reminder interval; resolution clears them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_SNOOZE_SECONDS = 24 * 60 * 60
MAX_CONNECTOR_ID_CHARS = 128
MAX_NOTICES = 256
_NOTICE_KEYS = frozenset({"connector_id", "events", "settings_deep_link", "dismissed_until", "dismissed_launch"})


@dataclass(frozen=True)
class Notice:
    connector_id: str
    events: tuple[str, ...]
    settings_deep_link: str
    dismissed_until: int | None = None
    dismissed_launch: int | None = None


def _plain_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative plain int")
    return value


def _validated_health(result: Any) -> tuple[str, tuple[str, ...], bool, str]:
    if type(result) is not dict:
        raise TypeError("health result must be a plain dict")
    cid = result.get("connector_id")
    events = result.get("events")
    important = result.get("important")
    link = result.get("settings_deep_link")
    if type(cid) is not str or not cid or len(cid) > MAX_CONNECTOR_ID_CHARS:
        raise ValueError("invalid connector_id")
    if type(events) is not tuple or any(type(x) is not str for x in events):
        raise ValueError("events must be a tuple of plain strings")
    if type(important) is not bool:
        raise ValueError("important must be a plain bool")
    expected = f"settings://connectors/{cid}"
    if type(link) is not str or link != expected:
        raise ValueError("invalid settings deep link")
    return cid, events, important, link


def _validated_snapshot_row(row: Any) -> Notice:
    if type(row) is not dict or frozenset(row.keys()) != _NOTICE_KEYS:
        raise ValueError("invalid notice snapshot row")
    cid = row["connector_id"]
    events = row["events"]
    link = row["settings_deep_link"]
    if type(cid) is not str or not cid or len(cid) > MAX_CONNECTOR_ID_CHARS:
        raise ValueError("invalid connector_id")
    if type(events) is not tuple or not events or any(type(x) is not str for x in events):
        raise ValueError("invalid notice events")
    if type(link) is not str or link != f"settings://connectors/{cid}":
        raise ValueError("invalid settings deep link")
    until = row["dismissed_until"]
    launch = row["dismissed_launch"]
    if (until is None) != (launch is None):
        raise ValueError("partial dismissal state")
    if until is not None:
        until = _plain_int(until, "dismissed_until")
        launch = _plain_int(launch, "dismissed_launch")
    return Notice(cid, events, link, until, launch)


class NoticeStore:
    def __init__(self) -> None:
        self._notices: dict[str, Notice] = {}

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> "NoticeStore":
        """Atomically restore detached persisted state; malformed data fails closed."""
        if type(snapshot) is not tuple or len(snapshot) > MAX_NOTICES:
            raise ValueError("invalid notice snapshot")
        restored: dict[str, Notice] = {}
        for row in snapshot:
            notice = _validated_snapshot_row(row)
            if notice.connector_id in restored:
                raise ValueError("duplicate connector notice")
            restored[notice.connector_id] = notice
        store = cls()
        store._notices = restored
        return store

    def reconcile(self, health_result: Any) -> None:
        """Atomically create/update/clear a notice from normalized health output."""
        cid, events, important, link = _validated_health(health_result)
        if not important or not events:
            self._notices.pop(cid, None)
            return
        old = self._notices.get(cid)
        keep_snooze = old is not None and old.events == events
        self._notices[cid] = Notice(
            cid, events, link,
            old.dismissed_until if keep_snooze else None,
            old.dismissed_launch if keep_snooze else None,
        )

    def dismiss(self, connector_id: Any, *, now: Any, launch_id: Any,
                snooze_seconds: Any = 3600) -> None:
        if type(connector_id) is not str:
            raise ValueError("connector_id must be a plain string")
        now_i = _plain_int(now, "now")
        launch_i = _plain_int(launch_id, "launch_id")
        snooze_i = _plain_int(snooze_seconds, "snooze_seconds")
        if snooze_i > MAX_SNOOZE_SECONDS:
            raise ValueError("snooze interval too large")
        notice = self._notices.get(connector_id)
        if notice is None:
            return
        self._notices[connector_id] = Notice(
            notice.connector_id, notice.events, notice.settings_deep_link,
            now_i + snooze_i, launch_i,
        )

    def visible(self, *, now: Any, launch_id: Any) -> tuple[Notice, ...]:
        now_i = _plain_int(now, "now")
        launch_i = _plain_int(launch_id, "launch_id")
        out = []
        for notice in self._notices.values():
            if (notice.dismissed_until is not None and now_i < notice.dismissed_until
                    and notice.dismissed_launch == launch_i):
                continue
            out.append(notice)
        return tuple(sorted(out, key=lambda n: n.connector_id))

    def snapshot(self) -> tuple[dict[str, Any], ...]:
        """Return detached, secret-free persistence data."""
        return tuple({
            "connector_id": n.connector_id,
            "events": n.events,
            "settings_deep_link": n.settings_deep_link,
            "dismissed_until": n.dismissed_until,
            "dismissed_launch": n.dismissed_launch,
        } for n in sorted(self._notices.values(), key=lambda x: x.connector_id))
