"""Pure-stdlib parking policy for Captain connector setup/health notices.

Production integration should adapt these semantics into Captain's canonical Settings
registry. No credentials, tokens, provider payloads, raw repository paths, or
secret-derived strings belong in notice state. Project-bound notices are
full-scope/epoch-bound and fail closed.
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
    # Keep connector notices on the same authority wall as Project Memory/context.
    # Only the stable repo scope hash may persist/render; raw machine/repo paths must
    # never enter notification state.
    keys = ("chat_id", "project_id", "repo_scope_hash", "state_epoch")
    values = tuple(connector.get(k) for k in keys)
    raw_repo_scope = connector.get("repo_scope")
    if raw_repo_scope is not None:
        raise ValueError("raw repo_scope is forbidden; use repo_scope_hash")
    if all(v is None for v in values):
        return None
    chat_id, project_id, repo_scope_hash, epoch = values
    if not all(isinstance(v, str) and v for v in (chat_id, project_id, repo_scope_hash)):
        raise ValueError("project connector notices require chat_id + project_id + repo_scope_hash + state_epoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
        raise ValueError("project connector notices require a positive integer state_epoch")
    return dict(zip(keys, values))


def notice_for(connector, now=None):
    """Return a secret-free persistent notice or None.

    Dismissal is temporary: an unresolved important issue reappears after remind_after.
    Resolution clears it automatically because healthy/ready state yields None.
    """
    now = _utc(now or datetime.now(timezone.utc))
    scope = _scope(connector)
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
    notice = {
        "connector_id": connector["connector_id"], "code": code,
        "important": code in IMPORTANT, "settings_section": section,
        "remind_after": remediation.get("remind_after"), "generated_at": now.isoformat(),
    }
    if scope is not None:
        notice.update(scope)
    return notice


def visible(notice, dismissed_at=None, now=None, *, chat_id=None, project_id=None, repo_scope_hash=None, state_epoch=None):
    if notice is None:
        return False
    keys = ("chat_id", "project_id", "repo_scope_hash", "state_epoch")
    stored = tuple(notice.get(k) for k in keys)
    requested = (chat_id, project_id, repo_scope_hash, state_epoch)
    if any(v is not None for v in stored):
        try:
            normalized = _scope(notice)
        except ValueError:
            return False
        if normalized is None or stored != requested:
            return False
    elif any(v is not None for v in requested):
        # Global notices may render in Settings, but never masquerade as project state.
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
