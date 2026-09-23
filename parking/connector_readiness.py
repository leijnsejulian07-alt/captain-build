"""Secret-free readiness evaluator for Captain Settings connectors.

Providers report normalized capability/auth health; Captain derives UI state and
never performs authentication, network calls, or paid API usage here.
"""
AUTH_METHODS = {"none", "oauth", "api_key", "id_based", "local_session"}
GOOD_AUTH = {"not_required", "valid"}
GOOD_VERSION = {"current"}
MAX_LABEL = 256
MAX_PERMISSIONS = 128


def _label(value, field, *, allow_empty=False):
    """Validate an inert, bounded provider-controlled label."""
    if type(value) is not str:
        raise TypeError(f"{field} must be a plain string")
    if (not allow_empty and not value) or len(value) > MAX_LABEL:
        raise ValueError(f"{field} invalid")
    return value


def evaluate(connector):
    """Return normalized Installed/Connected/Enabled/Ready state, fail closed."""
    if type(connector) is not dict:
        raise TypeError("connector must be a plain dict")
    connector_id = _label(connector.get("connector_id"), "connector_id")
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
        if len(permission) > MAX_LABEL:
            raise ValueError("permission too long")
        if permission.strip():
            permissions.append(permission)
    permissions = tuple(sorted(set(permissions)))

    health = connector.get("health")
    if type(health) is not dict:
        raise TypeError("health must be a plain dict")
    health_status = _label(health.get("status", "unknown"), "health.status")
    auth_status = _label(health.get("auth_status", "unknown"), "health.auth_status")
    version_status = _label(health.get("provider_version_status", "unknown"), "health.provider_version_status")
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
        "health": {"status": health_status, "auth_status": auth_status,
                   "provider_version_status": version_status},
    }
