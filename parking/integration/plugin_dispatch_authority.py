from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Mapping, Sequence

from parking.integration.plugin_settings_registry import (
    PluginSettingsError,
    authorize_plugin_dispatch,
    parse_plugin_state,
)
from parking.integration.scope_contract import MAX_STATE_EPOCH, parse_scope

SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CAP_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,95}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _epoch(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > MAX_STATE_EPOCH:
        raise ValueError("invalid state_epoch")
    return value


def _safe_id(name: str, value: object) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _capability(value: object) -> str:
    if not isinstance(value, str) or not _CAP_RE.fullmatch(value):
        raise ValueError("invalid capability")
    return value


def _state_fingerprint(record: Mapping[str, object]) -> str:
    state = parse_plugin_state(record)
    payload = {
        "plugin_id": state.plugin_id,
        "installed": state.installed,
        "connected": state.connected,
        "enabled": state.enabled,
        "ready": state.ready,
        "auth_method": state.auth_method,
        "scope": state.scope,
        "project_id": state.project_id,
        "capabilities": list(state.capabilities),
        "permissions": list(state.permissions),
        "health": state.health,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ticket_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_record(records: Sequence[Mapping[str, object]], plugin_id: str) -> Mapping[str, object]:
    target = _safe_id("plugin_id", plugin_id)
    matches = [record for record in records if isinstance(record, Mapping) and record.get("plugin_id") == target]
    if len(matches) != 1:
        raise PluginSettingsError("plugin authority must resolve exactly once")
    return matches[0]


def issue_plugin_dispatch_ticket(
    records: Sequence[Mapping[str, object]],
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    state_epoch: int,
    plugin_id: str,
    capability: str,
    required_permission: str | None = None,
) -> dict[str, object]:
    scope = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    epoch = _epoch(state_epoch)
    plugin = _safe_id("plugin_id", plugin_id)
    cap = _capability(capability)
    permission = _capability(required_permission) if required_permission is not None else None
    record = _resolve_record(records, plugin)
    state = parse_plugin_state(record)

    authorization = authorize_plugin_dispatch(
        records, plugin_id=plugin, capability=cap, project_id=scope.project_id
    )
    if authorization.get("allowed") is not True:
        raise PermissionError("plugin dispatch is not authorized")
    if permission is not None and permission not in state.permissions:
        raise PermissionError("plugin permission is not granted")

    ticket: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "scope": scope.as_dict(),
        "state_epoch": epoch,
        "plugin_id": plugin,
        "capability": cap,
        "required_permission": permission,
        "plugin_state_fingerprint": _state_fingerprint(record),
    }
    ticket["binding_digest"] = _ticket_digest(ticket)
    return ticket


def validate_plugin_dispatch_ticket(
    ticket: Mapping[str, object],
    records: Sequence[Mapping[str, object]],
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    current_state_epoch: int,
) -> dict[str, object]:
    required = {
        "schema_version",
        "scope",
        "state_epoch",
        "plugin_id",
        "capability",
        "required_permission",
        "plugin_state_fingerprint",
        "binding_digest",
    }
    if not isinstance(ticket, Mapping) or set(ticket) != required or ticket.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid plugin dispatch ticket schema")

    expected_scope = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    actual_scope = parse_scope(ticket.get("scope"))
    if actual_scope != expected_scope:
        raise PermissionError("plugin dispatch scope mismatch")

    ticket_epoch = _epoch(ticket.get("state_epoch"))
    if ticket_epoch != _epoch(current_state_epoch):
        raise PermissionError("plugin dispatch state epoch mismatch")

    plugin = _safe_id("plugin_id", ticket.get("plugin_id"))
    cap = _capability(ticket.get("capability"))
    permission_raw = ticket.get("required_permission")
    permission = _capability(permission_raw) if permission_raw is not None else None
    fingerprint = ticket.get("plugin_state_fingerprint")
    digest = ticket.get("binding_digest")
    if not isinstance(fingerprint, str) or not _DIGEST_RE.fullmatch(fingerprint):
        raise ValueError("invalid plugin state fingerprint")
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise ValueError("invalid plugin dispatch binding")

    unsigned = dict(ticket)
    unsigned.pop("binding_digest")
    if not hmac.compare_digest(digest, _ticket_digest(unsigned)):
        raise ValueError("plugin dispatch ticket was modified")

    record = _resolve_record(records, plugin)
    if not hmac.compare_digest(fingerprint, _state_fingerprint(record)):
        raise PermissionError("plugin settings changed after ticket issuance")
    state = parse_plugin_state(record)
    authorization = authorize_plugin_dispatch(
        records, plugin_id=plugin, capability=cap, project_id=expected_scope.project_id
    )
    if authorization.get("allowed") is not True:
        raise PermissionError("plugin dispatch is no longer authorized")
    if permission is not None and permission not in state.permissions:
        raise PermissionError("plugin permission is no longer granted")
    return dict(ticket)
