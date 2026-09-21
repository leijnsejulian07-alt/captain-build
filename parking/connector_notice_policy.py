"""Pure-stdlib parking policy for Captain connector setup/health notices.

Production integration should adapt these semantics into Captain's canonical Settings
registry. No credentials, tokens, provider payloads, or secret-derived strings belong
in notice state. Project-bound notices are epoch-bound and fail closed.
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


def _scope(connector):
    project_id = connector.get("project_id")
    epoch = connector.get("state_epoch")
    if project_id is None and epoch is None:
        return None, None
    if not isinstance(project_id, str) or not project_id or not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
        raise ValueError("project connector notices require project_id + non-negative integer state_epoch")
    return project_id, epoch


def notice_for(connector, now=None):
    """Return a secret-free persistent notice or None.

    Dismissal is temporary: an unresolved important issue reappears after remind_after.
    Resolution clears it automatically because healthy/ready state yields None.
    """
    now = _utc(now or datetime.now(timezone.utc))
    project_id, epoch = _scope(connector)
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
    notice = {
        "connector_id": connector["connector_id"],
        "code": code,
        "important": code in IMPORTANT,
        "settings_section": section,
        "remind_after": remind_after,
        "generated_at": now.isoformat(),
    }
    if project_id is not None:
        notice["project_id"] = project_id
        notice["state_epoch"] = epoch
    return notice


def visible(notice, dismissed_at=None, now=None, *, project_id=None, state_epoch=None):
    if notice is None:
        return False
    scoped_project = notice.get("project_id")
    scoped_epoch = notice.get("state_epoch")
    if scoped_project is not None or scoped_epoch is not None:
        if not isinstance(scoped_project, str) or not scoped_project or not isinstance(scoped_epoch, int) or isinstance(scoped_epoch, bool) or scoped_epoch < 0:
            return False
        if project_id != scoped_project or state_epoch != scoped_epoch:
            return False
    elif project_id is not None or state_epoch is not None:
        # Global notices may render in Settings, but never masquerade as project-scoped state.
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
