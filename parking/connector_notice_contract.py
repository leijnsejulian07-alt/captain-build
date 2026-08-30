from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping
import re

_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_IMPORTANT = {"connect", "reconnect", "update-setup", "test-connection"}

class ConnectorNoticeError(ValueError):
    pass

@dataclass(frozen=True)
class ConnectorNotice:
    connector_id: str
    scope_hash: str
    remediation: str
    settings_section: str
    first_seen_at: int
    dismissed_until: int | None = None

    def visible(self, now: int, resolved: bool) -> bool:
        if resolved:
            return False
        return self.dismissed_until is None or now >= self.dismissed_until

def _scope_hash(project_id: str | None) -> str:
    scope = project_id or "global"
    if not scope.strip() or len(scope) > 128:
        raise ConnectorNoticeError("invalid scope")
    return sha256(scope.encode("utf-8")).hexdigest()

def make_notice(connector_id: str, remediation: str, now: int,
                project_id: str | None = None) -> ConnectorNotice:
    if not _ID.fullmatch(connector_id):
        raise ConnectorNoticeError("invalid connector_id")
    if remediation not in _IMPORTANT:
        raise ConnectorNoticeError("non-persistent remediation")
    if now < 0:
        raise ConnectorNoticeError("invalid timestamp")
    return ConnectorNotice(connector_id, _scope_hash(project_id), remediation,
                           f"connectors/{connector_id}", now)

def dismiss(notice: ConnectorNotice, now: int, reminder_seconds: int = 86400) -> ConnectorNotice:
    if now < notice.first_seen_at or not 3600 <= reminder_seconds <= 604800:
        raise ConnectorNoticeError("invalid dismissal")
    return ConnectorNotice(notice.connector_id, notice.scope_hash, notice.remediation,
                           notice.settings_section, notice.first_seen_at,
                           now + reminder_seconds)

def public_payload(notice: ConnectorNotice) -> Mapping[str, object]:
    return {"connector_id": notice.connector_id, "scope_hash": notice.scope_hash,
            "remediation": notice.remediation, "settings_section": notice.settings_section,
            "first_seen_at": notice.first_seen_at,
            "dismissed_until": notice.dismissed_until}
