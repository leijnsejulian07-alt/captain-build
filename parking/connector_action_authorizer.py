"""Fail-closed per-action authorization for Captain connector dispatch.

This module is deliberately side-effect free. Call it immediately before a
connector action is dispatched; provider authentication never substitutes for
Captain authorization.
"""
import re

MAX_ACTION = 128
ACTION_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")


def _valid_action(value):
    return (
        type(value) is str
        and 0 < len(value) <= MAX_ACTION
        and value == value.strip()
        and ACTION_RE.fullmatch(value) is not None
        and "*" not in value
    )


def authorize(connector_state, action):
    """Return a small decision object; malformed/implicit authority is denied."""
    if type(connector_state) is not dict:
        return {"allowed": False, "reason": "invalid_state"}
    if not _valid_action(action):
        return {"allowed": False, "reason": "invalid_action"}

    for key in ("installed", "connected", "enabled", "ready"):
        if connector_state.get(key) is not True:
            return {"allowed": False, "reason": "connector_not_ready"}

    permissions = connector_state.get("permissions")
    if type(permissions) not in (list, tuple):
        return {"allowed": False, "reason": "invalid_permissions"}
    if len(permissions) > 128:
        return {"allowed": False, "reason": "invalid_permissions"}

    seen = set()
    for permission in permissions:
        if not _valid_action(permission) or permission in seen:
            return {"allowed": False, "reason": "invalid_permissions"}
        seen.add(permission)

    if action not in seen:
        return {"allowed": False, "reason": "permission_denied"}
    return {"allowed": True, "reason": "authorized"}
