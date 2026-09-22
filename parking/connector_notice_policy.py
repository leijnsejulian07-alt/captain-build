"""Pure-stdlib parking policy for Captain connector setup/health notices.

Production integration should adapt these semantics into Captain's canonical Settings
registry. No credentials, tokens, provider payloads, raw repository paths, or
secret-derived strings belong in notice state. Project-bound notices are
full-scope/epoch-bound and fail closed.
"""
from datetime import datetime, timedelta, timezone
import re

try:
    from .connector_readiness import evaluate as evaluate_readiness
except ImportError:  # direct execution from parking/
    from connector_readiness import evaluate as evaluate_readiness

IMPORTANT = {"auth_expired", "auth_invalid", "reauth_required", "provider_deprecated", "migration_required", "setup_incomplete"}
DEFAULT_REMINDER = timedelta(hours=24)
CONNECTOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _utc(value):
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise TypeError("datetime required")
    if value.tzinfo is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _connector_id(connector):
    value = connector.get("connector_id")
    if not isinstance(value, str) or not CONNECTOR_ID.fullmatch(value):
        raise ValueError("connector_id must be a non-secret canonical slug")
    return value


def _settings_section(connector_id, remediation):
    """Accept only deep links inside the owning connector's Settings subtree.

    Provider supplied URLs/paths must never become executable/navigation targets in
    persistent notices. Binding the first path segment to connector_id also prevents
    one connector from steering remediation into another connector's settings.
    """
    default = f"settings/connectors/{connector_id}"
    value = remediation.get("settings_section")
    if value is None:
        return default
    if not isinstance(value, str) or not value.startswith("settings/connectors/"):
        raise ValueError("settings_section must be a Captain connector Settings deep link")
    suffix = value[len("settings/connectors/"):]
    parts = suffix.split("/")
    if not suffix or any(part in ("", ".", "..") for part in parts):
        raise ValueError("invalid connector Settings deep link")
    if parts[0] != connector_id:
        raise ValueError("settings_section must remain inside the owning connector subtree")
    return value


def _scope(connector):
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
    """Return a secret-free persistent notice or None."""
    now = _utc(now or datetime.now(timezone.utc))
    connector_id = _connector_id(connector)
    scope = _scope(connector)
    normalized = evaluate_readiness(connector)
    h = normalized["health"]
    if normalized["ready"]:
        return None

    code = None
    auth = h.get("auth_status")
    version = h.get("provider_version_status")
    if auth == "expired": code = "auth_expired"
    elif auth == "invalid": code = "auth_invalid"
    elif auth == "reauth_required": code = "reauth_required"
    elif version == "migration_required": code = "migration_required"
    elif version == "deprecated": code = "provider_deprecated"
    elif normalized.get("installed") and not normalized.get("connected"): code = "setup_incomplete"
    if code is None:
        return None

    remediation = connector.get("remediation") or {}
    if not isinstance(remediation, dict):
        raise ValueError("remediation must be an object")
    section = _settings_section(connector_id, remediation)
    notice = {
        "connector_id": connector_id, "code": code,
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
