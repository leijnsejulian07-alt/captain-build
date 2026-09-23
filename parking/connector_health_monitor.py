"""Pure connector health/migration monitor for Captain Settings.

Providers report normalized metadata; Captain derives notices. No secrets, network
calls, auth bypass, or paid-service activation belongs in this layer.
"""

KNOWN_AUTH = {"none", "oauth", "api_key", "id_based", "local_session"}
IMPORTANT = {"auth_expired", "auth_method_migration", "provider_deprecated", "setup_changed"}


def evaluate(previous, current):
    """Return stable, secret-free health events; malformed input fails closed."""
    if type(current) is not dict:
        raise TypeError("current connector state must be a plain dict")
    cid = current.get("connector_id")
    if type(cid) is not str or not cid.strip():
        raise ValueError("connector_id required")
    if previous is not None and type(previous) is not dict:
        raise TypeError("previous connector state must be a plain dict")

    events = []
    auth = current.get("auth_method")
    if auth not in KNOWN_AUTH:
        events.append("setup_changed")

    health = current.get("health")
    if type(health) is not dict:
        health = {}
    if health.get("auth_status") in {"expired", "invalid", "revoked"}:
        events.append("auth_expired")
    if health.get("provider_version_status") in {"deprecated", "unsupported"}:
        events.append("provider_deprecated")
    if health.get("setup_status") == "changed":
        events.append("setup_changed")

    if previous is not None:
        old_auth = previous.get("auth_method")
        if old_auth in KNOWN_AUTH and auth in KNOWN_AUTH and old_auth != auth:
            events.append("auth_method_migration")

    # Stable de-duplication; output contains codes only, never provider diagnostics.
    ordered = tuple(dict.fromkeys(events))
    return {
        "connector_id": cid.strip(),
        "events": ordered,
        "important": any(code in IMPORTANT for code in ordered),
        "settings_deep_link": f"settings://connectors/{cid.strip()}",
    }
