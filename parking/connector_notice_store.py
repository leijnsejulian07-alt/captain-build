"""Scoped persistent connector notices for Captain Settings.

Pure state logic only: no provider calls, credentials, diagnostics, or secret material.
Important unresolved notices can be snoozed, but become visible again after the
reminder interval or on a later launch. Resolution removes them automatically.
"""

from dataclasses import dataclass
import math

DEFAULT_REMINDER_SECONDS = 24 * 60 * 60
MAX_ACTIVE_CODES_PER_CONNECTOR = 64


@dataclass(frozen=True)
class NoticeKey:
    scope_id: str
    connector_id: str
    code: str


class ConnectorNoticeStore:
    def __init__(self, reminder_seconds=DEFAULT_REMINDER_SECONDS):
        if type(reminder_seconds) is not int or reminder_seconds <= 0:
            raise ValueError("reminder_seconds must be a positive int")
        self._reminder_seconds = reminder_seconds
        self._items = {}

    @staticmethod
    def _label(value, name):
        if type(value) is not str or not value.strip() or len(value) > 512:
            raise ValueError(f"{name} must be a non-empty bounded string")
        return value.strip()

    @classmethod
    def _key(cls, scope_id, connector_id, code):
        return NoticeKey(
            cls._label(scope_id, "scope_id"),
            cls._label(connector_id, "connector_id"),
            cls._label(code, "code"),
        )

    @staticmethod
    def _time(now):
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError("now must be a finite non-negative number")
        return now

    def reconcile(self, scope_id, connector_id, active_codes, now):
        """Replace active codes for one scoped connector; resolved notices disappear."""
        scope_id = self._label(scope_id, "scope_id")
        connector_id = self._label(connector_id, "connector_id")
        if type(active_codes) is not tuple or any(type(code) is not str for code in active_codes):
            raise TypeError("active_codes must be a tuple of plain strings")
        if len(active_codes) > MAX_ACTIVE_CODES_PER_CONNECTOR:
            raise ValueError("too many active connector notice codes")
        now = self._time(now)
        normalized = tuple(dict.fromkeys(self._label(code, "code") for code in active_codes))
        desired = {self._key(scope_id, connector_id, code) for code in normalized}
        for key in tuple(self._items):
            if key.scope_id == scope_id and key.connector_id == connector_id and key not in desired:
                del self._items[key]
        for key in desired:
            self._items.setdefault(key, {"first_seen": now, "snoozed_until": None})

    def dismiss_temporarily(self, scope_id, connector_id, code, now):
        key = self._key(scope_id, connector_id, code)
        if key not in self._items:
            return False
        now = self._time(now)
        self._items[key]["snoozed_until"] = now + self._reminder_seconds
        return True

    def visible(self, scope_id, now, launch=False):
        """Return secret-free notices for exactly one scope.

        A later launch re-surfaces unresolved notices even if their timer has not yet
        elapsed; this intentionally matches Captain's persistent remediation UX.
        """
        scope_id = self._label(scope_id, "scope_id")
        now = self._time(now)
        out = []
        for key, state in self._items.items():
            if key.scope_id != scope_id:
                continue
            until = state["snoozed_until"]
            if launch or until is None or now >= until:
                out.append({
                    "connector_id": key.connector_id,
                    "code": key.code,
                    "settings_deep_link": f"settings://connectors/{key.connector_id}",
                })
        return tuple(sorted(out, key=lambda x: (x["connector_id"], x["code"])))
