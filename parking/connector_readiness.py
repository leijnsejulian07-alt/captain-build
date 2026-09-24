"""Secret-free readiness evaluator for Captain Settings connectors.

Providers report normalized capability/auth health; Captain derives UI state and
never performs authentication, network calls, or paid API usage here.
"""
import re
from datetime import datetime

AUTH_METHODS = {"none", "oauth", "api_key", "id_based", "local_session"}
HEALTH_STATUSES = {"unknown", "healthy", "degraded", "blocked"}
AUTH_STATUSES = {"not_required", "unknown", "valid", "expired", "invalid", "reauth_required"}
VERSION_STATUSES = {"unknown", "current", "deprecated", "migration_required"}
GOOD_AUTH = {"not_required", "valid"}
GOOD_VERSION = {"current"}
MAX_LABEL = 256
MAX_CONNECTOR_ID = 128
MAX_PERMISSION_LABEL = 128
MAX_PERMISSIONS = 128
CONNECTOR_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$")


def _label(value, field, *, allow_empty=False, max_length=MAX_LABEL):
    """Validate an inert, bounded provider-controlled label."""
    if type(value) is not str:
        raise TypeError(f"{field} must be a plain string")
    if (not allow_empty and not value) or len(value) > max_length:
        raise ValueError(f"{field} invalid")
    return value


def _enum(value, field, allowed):
    """Normalize provider-controlled enum values without reflecting diagnostics."""
    value = _label(value, field)
    return value if value in allowed else "unknown"


def _checked_at(value):
    """Preserve only a bounded, real RFC3339 instant; malformed metadata is null."""
    if value is None:
        return None
    if type(value) is not str or len(value) > MAX_LABEL or RFC3339_RE.fullmatch(value) is None:
        return None
    try:
        datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return value


def evaluate(connector):
    """Return normalized Installed/Connected/Enabled/Ready state, fail closed."""
    if type(connector) is not dict:
        raise TypeError("connector must be a plain dict")
    connector_id = _label(connector.get("connector_id"), "connector_id", max_length=MAX_CONNECTOR_ID)
    if CONNECTOR_ID_RE.fullmatch(connector_id) is None:
        raise ValueError("connector_id invalid")
    installed = connector.get("installed") is True
    connected = installed and connector.get("connected") is True
    enabled = connected and connector.get("enabled") is True
    raw_auth_method = connector.get("auth_method")
    auth_method_known = type(raw_auth_method) is str and len(raw_auth_method) <= MAX_LABEL and raw_auth_method in AUTH_METHODS
    auth_method = raw_auth_method if auth_method_known else "none"

    raw_permissions = connector.get("permissions", [])
    if type(raw_permissions) not in (list, tuple):
        raise TypeError("permissions must be a plain list or tuple")
    if len(raw_permissions) > MAX_PERMISSIONS:
        raise ValueError("too many permissions")
    permissions = []
    for permission in raw_permissions:
        if type(permission) is not str:
            continue
        if len(permission) > MAX_PERMISSION_LABEL:
            raise ValueError("permission too long")
        if permission.strip():
            permissions.append(permission)
    permissions = tuple(sorted(set(permissions)))

    health = connector.get("health")
    if type(health) is not dict:
        raise TypeError("health must be a plain dict")
    health_status = _enum(health.get("status", "unknown"), "health.status", HEALTH_STATUSES)
    auth_status = _enum(health.get("auth_status", "unknown"), "health.auth_status", AUTH_STATUSES)
    version_status = _enum(health.get("provider_version_status", "unknown"), "health.provider_version_status", VERSION_STATUSES)
    # checked_at is metadata, never authority. Preserve only a real RFC3339 instant;
    # malformed/provider-controlled values become null rather than leaking diagnostics.
    checked_at = _checked_at(health.get("checked_at"))
    auth_ok = auth_method_known and auth_status in GOOD_AUTH
    if auth_method != "none" and auth_status == "not_required": auth_ok = False
    if auth_method == "none" and auth_status != "not_required": auth_ok = False

    blockers = []
    if not installed: blockers.append("not_installed")
    elif not connected: blockers.append("not_connected")
    elif not enabled: blockers.append("disabled")
    if not auth_method_known: blockers.append("auth_method_invalid")
    elif not auth_ok: blockers.append("auth_unhealthy")
    if health_status != "healthy": blockers.append("health_unhealthy")
    if version_status != "current": blockers.append("provider_compatibility_unverified")
    ready = bool(installed and connected and enabled and health_status == "healthy" and auth_ok and version_status in GOOD_VERSION)
    if ready: blockers = []
    return {
        "connector_id": connector_id, "installed": installed, "connected": connected,
        "enabled": enabled, "ready": ready, "auth_method": auth_method,
        "permissions": permissions, "blockers": tuple(blockers),
        "health": {"status": health_status, "checked_at": checked_at,
                   "auth_status": auth_status, "provider_version_status": version_status},
    }
