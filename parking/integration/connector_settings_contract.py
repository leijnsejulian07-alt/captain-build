from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json

ALLOWED_AUTH = {"oauth", "api_key", "id", "local", "none"}
ALLOWED_HEALTH = {"healthy", "degraded", "invalid_auth", "expired_auth", "setup_required", "deprecated"}
ALLOWED_PERMS = {"read", "write", "admin", "repo", "calendar", "mail", "files", "browser"}


class ContractError(ValueError):
    pass


def _strict_keys(value: dict, allowed: set[str], required: set[str]) -> None:
    if set(value) - allowed:
        raise ContractError("unknown fields")
    if not required <= set(value):
        raise ContractError("missing fields")


def _clean_text(value: object, max_len: int = 120) -> str:
    if not isinstance(value, str) or not value or len(value) > max_len or value.strip() != value:
        raise ContractError("invalid text")
    return value


def _fingerprint(connector_id: str, issue_code: str, project_id: str) -> str:
    raw = json.dumps([connector_id, issue_code, project_id], separators=(",", ":"), ensure_ascii=True)
    return sha256(raw.encode("utf-8")).hexdigest()


def validate_connector_state(state: dict) -> bool:
    fields = {
        "schema_version", "connector_id", "project_id", "installed", "connected", "enabled", "ready",
        "auth_method", "health", "permissions_granted", "permissions_required", "issue_code",
    }
    _strict_keys(state, fields, fields)
    if state["schema_version"] != 1:
        raise ContractError("schema")
    _clean_text(state["connector_id"], 80)
    _clean_text(state["project_id"], 80)
    for key in ("installed", "connected", "enabled", "ready"):
        if type(state[key]) is not bool:
            raise ContractError(key)
    if state["auth_method"] not in ALLOWED_AUTH:
        raise ContractError("auth")
    if state["health"] not in ALLOWED_HEALTH:
        raise ContractError("health")
    for key in ("permissions_granted", "permissions_required"):
        permissions = state[key]
        if (
            not isinstance(permissions, list)
            or len(permissions) > 32
            or len(permissions) != len(set(permissions))
            or any(permission not in ALLOWED_PERMS for permission in permissions)
        ):
            raise ContractError(key)
    issue = state["issue_code"]
    if issue is not None:
        _clean_text(issue, 80)
    expected_ready = (
        state["installed"]
        and state["connected"]
        and state["enabled"]
        and state["health"] == "healthy"
        and set(state["permissions_required"]) <= set(state["permissions_granted"])
    )
    if state["ready"] != expected_ready:
        raise ContractError("ready mismatch")
    if state["connected"] and not state["installed"]:
        raise ContractError("connected without installed")
    if state["enabled"] and not state["installed"]:
        raise ContractError("enabled without installed")
    if state["auth_method"] == "oauth" and not state["connected"] and state["health"] == "healthy":
        raise ContractError("healthy oauth disconnected")
    if state["health"] != "healthy" and issue is None:
        raise ContractError("unhealthy requires issue")
    if state["health"] == "healthy" and issue is not None:
        raise ContractError("healthy cannot carry issue")
    return True


def build_notice(
    state: dict,
    remediation_path: str,
    now: datetime,
    dismiss_until: datetime | None = None,
) -> dict | None:
    validate_connector_state(state)
    if state["ready"]:
        return None
    _clean_text(remediation_path, 200)
    if not remediation_path.startswith("settings://connectors/"):
        raise ContractError("bad remediation")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ContractError("now")
    if dismiss_until is not None:
        if not isinstance(dismiss_until, datetime) or dismiss_until.tzinfo is None:
            raise ContractError("dismiss")
        if dismiss_until > now + timedelta(days=7):
            raise ContractError("dismiss too long")
    issue = state["issue_code"] or "not_ready"
    return {
        "schema_version": 1,
        "connector_id": state["connector_id"],
        "project_id": state["project_id"],
        "issue_code": issue,
        "notice_fingerprint": _fingerprint(state["connector_id"], issue, state["project_id"]),
        "remediation_path": remediation_path,
        "dismiss_until": dismiss_until.isoformat() if dismiss_until else None,
        "secret_fields": [],
    }


def should_surface(notice: dict | None, state: dict, now: datetime) -> bool:
    validate_connector_state(state)
    if state["ready"]:
        return False
    if notice is None:
        return True
    fields = {
        "schema_version", "connector_id", "project_id", "issue_code", "notice_fingerprint",
        "remediation_path", "dismiss_until", "secret_fields",
    }
    _strict_keys(notice, fields, fields)
    if notice["schema_version"] != 1 or notice["secret_fields"] != []:
        raise ContractError("notice schema")
    if notice["connector_id"] != state["connector_id"] or notice["project_id"] != state["project_id"]:
        raise ContractError("scope mismatch")
    issue = state["issue_code"] or "not_ready"
    if notice["notice_fingerprint"] != _fingerprint(state["connector_id"], issue, state["project_id"]):
        return True
    dismiss_until = notice["dismiss_until"]
    if dismiss_until is None:
        return True
    return now >= datetime.fromisoformat(dismiss_until)
