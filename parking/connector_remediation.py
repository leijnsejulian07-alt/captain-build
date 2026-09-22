"""Safe, deterministic remediation plan for Captain Settings connectors.

Consumes only normalized output from connector_readiness.evaluate(). It never performs
authentication/network calls and never reflects provider error text or secrets.
"""
import re

_ACTIONS = {
    "not_installed": ("install", "Install connector", "settings/connectors"),
    "not_connected": ("connect", "Connect", "settings/connectors"),
    "disabled": ("enable", "Enable", "settings/connectors"),
    "auth_method_invalid": ("review_setup", "Review setup", "settings/connectors"),
    "auth_unhealthy": ("reconnect", "Reconnect", "settings/connectors"),
    "health_unhealthy": ("test_connection", "Test connection", "settings/connectors"),
    "provider_compatibility_unverified": ("review_provider", "Review provider update", "settings/connectors"),
}
_SAFE_CONNECTOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def remediation(readiness):
    """Return secret-free ordered UI actions from normalized readiness state.

    Unknown blocker codes fail closed into a generic review action rather than being
    rendered. OAuth/API-key details remain owned by the connector's official setup UI.
    Connector IDs are path segments, so malformed IDs are rejected rather than embedded
    into Settings deep links.
    """
    if not isinstance(readiness, dict):
        raise TypeError("readiness must be a dict")
    connector_id = readiness.get("connector_id")
    if not isinstance(connector_id, str) or not _SAFE_CONNECTOR_ID.fullmatch(connector_id):
        raise ValueError("valid connector_id required")
    if readiness.get("ready") is True:
        return ()

    blockers = readiness.get("blockers")
    if not isinstance(blockers, (list, tuple)):
        blockers = ()

    result = []
    seen = set()
    for blocker in blockers:
        if blocker in seen or not isinstance(blocker, str):
            continue
        seen.add(blocker)
        action = _ACTIONS.get(blocker)
        if action is None:
            action = ("review_setup", "Review setup", "settings/connectors")
        result.append({
            "connector_id": connector_id,
            "reason": blocker if blocker in _ACTIONS else "unknown_blocker",
            "action": action[0],
            "label": action[1],
            "deep_link": action[2] + "/" + connector_id,
        })
    return tuple(result)
