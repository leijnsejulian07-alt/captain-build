"""Secret-free readiness evaluator for Captain Settings connectors.

This is a dependency-free continuity implementation. Captain remains the authority:
providers report normalized capability/auth health, while this module derives the UI
state and never performs authentication, network calls, or paid API usage.
"""

AUTH_METHODS = {"none", "oauth", "api_key", "id_based", "local_session"}
GOOD_AUTH = {"not_required", "valid"}
GOOD_VERSION = {"current"}


def evaluate(connector):
    """Return normalized Installed/Connected/Enabled/Ready state, fail closed.

    `ready` is always derived, never trusted from persisted/provider input.
    Unknown/malformed health cannot become Ready. Permissions are normalized to a
    sorted tuple of non-empty strings so UI comparisons are deterministic.
    """
    if not isinstance(connector, dict):
        raise TypeError("connector must be a dict")
    connector_id = connector.get("connector_id")
    if not isinstance(connector_id, str) or not connector_id:
        raise ValueError("connector_id required")

    installed = connector.get("installed") is True
    connected = installed and connector.get("connected") is True
    enabled = connected and connector.get("enabled") is True
    auth_method = connector.get("auth_method")
    if auth_method not in AUTH_METHODS:
        auth_method = "none"

    raw_permissions = connector.get("permissions", [])
    if not isinstance(raw_permissions, (list, tuple)):
        raw_permissions = []
    permissions = tuple(sorted({p for p in raw_permissions if isinstance(p, str) and p.strip()}))

    health = connector.get("health")
    if not isinstance(health, dict):
        health = {}
    health_status = health.get("status", "unknown")
    auth_status = health.get("auth_status", "unknown")
    version_status = health.get("provider_version_status", "unknown")

    # Auth-bearing connectors may never be Ready with unknown auth. `none` is only
    # Ready when the provider explicitly reports auth as not_required.
    auth_ok = auth_status in GOOD_AUTH
    if auth_method != "none" and auth_status == "not_required":
        auth_ok = False
    if auth_method == "none" and auth_status != "not_required":
        auth_ok = False

    # Version/capability health must be positively known. Treating `unknown` as good
    # would let a stale provider silently remain Ready after an unobserved migration.
    ready = bool(
        installed and connected and enabled
        and health_status == "healthy"
        and auth_ok
        and version_status in GOOD_VERSION
    )

    return {
        "connector_id": connector_id,
        "installed": installed,
        "connected": connected,
        "enabled": enabled,
        "ready": ready,
        "auth_method": auth_method,
        "permissions": permissions,
        "health": {
            "status": health_status,
            "auth_status": auth_status,
            "provider_version_status": version_status,
        },
    }
