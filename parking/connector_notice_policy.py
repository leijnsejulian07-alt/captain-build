"""Pure-stdlib parking policy for Captain connector setup/health notices.

Production integration should adapt these semantics into Captain's canonical Settings
registry. No credentials, tokens, provider payloads, or secret-derived strings belong
in notice state.
"""
from datetime import datetime, timedelta, timezone

IMPORTANT = {"auth_expired", "auth_invalid", "reauth_required", "provider_deprecated", "migration_required", "setup_incomplete"}
DEFAULT_REMINDER = timedelta(hours=24)


def _utc(value):
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise TypeError("datetime required")
    if value.tzinfo is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def notice_for(connector, now=None):
    """Return a secret-free persistent notice or None.

    Dismissal is temporary: an unresolved important issue reappears after remind_after.
    Resolution clears it automatically because healthy/ready state yields None.
    """
    now = _utc(now or datetime.now(timezone.utc))
    h = connector["health"]
    if connector.get("ready") and h.get("status") == "healthy":
        return None

    code = None
    auth = h.get("auth_status")
    version = h.get("provider_version_status")
    if auth == "expired": code = "auth_expired"
    elif auth == "invalid": code = "auth_invalid"
    elif auth == "reauth_required": code = "reauth_required"
    elif version == "migration_required": code = "migration_required"
    elif version == "deprecated": code = "provider_deprecated"
    elif connector.get("installed") and not connector.get("connected"): code = "setup_incomplete"
    if code is None:
        return None

    remediation = connector.get("remediation") or {}
    section = remediation.get("settings_section")
    if not isinstance(section, str) or not section:
        section = f"settings/connectors/{connector['connector_id']}"
    remind_after = remediation.get("remind_after")
    # Persist only normalized, non-secret UI state.
    return {
        "connector_id": connector["connector_id"],
        "code": code,
        "important": code in IMPORTANT,
        "settings_section": section,
        "remind_after": remind_after,
        "generated_at": now.isoformat(),
    }


def visible(notice, dismissed_at=None, now=None):
    if notice is None:
        return False
    now = _utc(now or datetime.now(timezone.utc))
    dismissed_at = _utc(dismissed_at)
    if dismissed_at is None:
        return True
    raw = notice.get("remind_after")
    if raw:
        try:
            deadline = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except (ValueError, AttributeError):
            deadline = dismissed_at + DEFAULT_REMINDER
    else:
        deadline = dismissed_at + DEFAULT_REMINDER
    return now >= deadline
