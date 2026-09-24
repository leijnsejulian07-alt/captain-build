"""Pure connector health/migration monitor for Captain Settings.

Providers report normalized metadata; Captain derives notices. No secrets, network
calls, auth bypass, or paid-service activation belongs in this layer.
"""
from __future__ import annotations

import re
from typing import Any

KNOWN_AUTH = {"none", "oauth", "api_key", "id_based", "local_session"}
IMPORTANT = {"auth_expired", "auth_method_migration", "provider_deprecated", "setup_changed"}
MAX_CONNECTOR_ID_CHARS = 128
_CONNECTOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _plain_optional_string(value: Any) -> str | None:
    """Normalize provider metadata without invoking caller-defined scalar hooks."""
    return value if type(value) is str else None


def _connector_id(value: Any) -> str:
    if type(value) is not str:
        raise ValueError("connector_id must be a plain string")
    cid = value.strip()
    if not cid or len(cid) > MAX_CONNECTOR_ID_CHARS or _CONNECTOR_ID.fullmatch(cid) is None:
        raise ValueError("connector_id invalid")
    return cid


def evaluate(previous: Any, current: Any) -> dict[str, Any]:
    """Return stable, secret-free health events; malformed input fails closed."""
    if type(current) is not dict:
        raise TypeError("current connector state must be a plain dict")
    cid = _connector_id(current.get("connector_id"))
    if previous is not None and type(previous) is not dict:
        raise TypeError("previous connector state must be a plain dict")

    events: list[str] = []
    auth = _plain_optional_string(current.get("auth_method"))
    if auth not in KNOWN_AUTH:
        events.append("setup_changed")

    health = current.get("health")
    if type(health) is not dict:
        health = {}
    auth_status = _plain_optional_string(health.get("auth_status"))
    version_status = _plain_optional_string(health.get("provider_version_status"))
    setup_status = _plain_optional_string(health.get("setup_status"))
    if auth_status in {"expired", "invalid", "revoked"}:
        events.append("auth_expired")
    if version_status in {"deprecated", "unsupported"}:
        events.append("provider_deprecated")
    if setup_status == "changed":
        events.append("setup_changed")

    if previous is not None:
        old_auth = _plain_optional_string(previous.get("auth_method"))
        if old_auth in KNOWN_AUTH and auth in KNOWN_AUTH and old_auth != auth:
            events.append("auth_method_migration")

    # Stable de-duplication; output contains codes only, never provider diagnostics.
    ordered = tuple(dict.fromkeys(events))
    return {
        "connector_id": cid,
        "events": ordered,
        "important": any(code in IMPORTANT for code in ordered),
        "settings_deep_link": f"settings://connectors/{cid}",
    }
