"""Validated persistence codec for Captain connector UI replay state.

Only secret-free event bridge state is accepted. Unknown fields fail closed so future
credential-bearing additions cannot silently enter persisted notification state.
"""
from __future__ import annotations

from typing import Any

from .connector_settings import ConnectorError

_ALLOWED_TOP = frozenset({"sequence", "last_status", "notice_open"})
_ALLOWED_STATUS = frozenset({"project_id", "connector_id", "status"})
_ALLOWED_NOTICE = frozenset({"project_id", "connector_id", "open"})
_FORBIDDEN_FRAGMENTS = ("token", "secret", "api_key", "password", "credential", "auth_material")


def _safe_key(key: str) -> bool:
    lowered = key.lower()
    return not any(fragment in lowered for fragment in _FORBIDDEN_FRAGMENTS)


def _validate_scalar_tree(value: Any) -> None:
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, list):
        for item in value:
            _validate_scalar_tree(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not _safe_key(key):
                raise ConnectorError("unsafe checkpoint field")
            _validate_scalar_tree(item)
        return
    raise ConnectorError("unsupported checkpoint value")


def validate_connector_checkpoint(checkpoint: dict) -> dict:
    """Return a normalized secret-free checkpoint or fail closed."""
    if not isinstance(checkpoint, dict) or set(checkpoint) != _ALLOWED_TOP:
        raise ConnectorError("invalid checkpoint schema")
    sequence = checkpoint["sequence"]
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise ConnectorError("invalid checkpoint sequence")

    last_status = checkpoint["last_status"]
    notice_open = checkpoint["notice_open"]
    if not isinstance(last_status, list) or not isinstance(notice_open, list):
        raise ConnectorError("invalid checkpoint collections")

    seen_status: set[tuple[object, str]] = set()
    normalized_status = []
    for row in last_status:
        if not isinstance(row, dict) or set(row) != _ALLOWED_STATUS:
            raise ConnectorError("invalid status checkpoint row")
        project_id, connector_id, status = row["project_id"], row["connector_id"], row["status"]
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ConnectorError("invalid project scope")
        if not isinstance(connector_id, str) or not connector_id.strip() or not isinstance(status, dict):
            raise ConnectorError("invalid connector status row")
        _validate_scalar_tree(status)
        key = (project_id, connector_id)
        if key in seen_status:
            raise ConnectorError("duplicate status checkpoint row")
        seen_status.add(key)
        normalized_status.append({"project_id": project_id, "connector_id": connector_id, "status": dict(status)})

    seen_notice: set[tuple[object, str]] = set()
    normalized_notice = []
    for row in notice_open:
        if not isinstance(row, dict) or set(row) != _ALLOWED_NOTICE:
            raise ConnectorError("invalid notice checkpoint row")
        project_id, connector_id, is_open = row["project_id"], row["connector_id"], row["open"]
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ConnectorError("invalid project scope")
        if not isinstance(connector_id, str) or not connector_id.strip() or not isinstance(is_open, bool):
            raise ConnectorError("invalid notice checkpoint row")
        key = (project_id, connector_id)
        if key in seen_notice:
            raise ConnectorError("duplicate notice checkpoint row")
        seen_notice.add(key)
        normalized_notice.append({"project_id": project_id, "connector_id": connector_id, "open": is_open})

    return {"sequence": sequence, "last_status": normalized_status, "notice_open": normalized_notice}
