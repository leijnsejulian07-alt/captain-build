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


def _version_tuple(value: object) -> tuple[int, ...]:
    text = _clean_text(value, 40)
    parts = text.split(".")
    if not (1 <= len(parts) <= 4) or any(not part.isdigit() for part in parts):
        raise ContractError("invalid version")
    return tuple(int(part) for part in parts)


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


def validate_provider_expectation(expectation: dict) -> bool:
    fields = {
        "schema_version", "connector_id", "auth_method", "setup_version",
        "minimum_client_version", "deprecated_auth_methods",
    }
    _strict_keys(expectation, fields, fields)
    if expectation["schema_version"] != 1:
        raise ContractError("provider schema")
    _clean_text(expectation["connector_id"], 80)
    if expectation["auth_method"] not in ALLOWED_AUTH:
        raise ContractError("provider auth")
    _clean_text(expectation["setup_version"], 40)
    _version_tuple(expectation["minimum_client_version"])
    deprecated = expectation["deprecated_auth_methods"]
    if (
        not isinstance(deprecated, list)
        or len(deprecated) > len(ALLOWED_AUTH)
        or len(deprecated) != len(set(deprecated))
        or any(method not in ALLOWED_AUTH for method in deprecated)
        or expectation["auth_method"] in deprecated
    ):
        raise ContractError("deprecated auth")
    return True


def evaluate_provider_compatibility(state: dict, expectation: dict, observed: dict) -> dict:
    validate_connector_state(state)
    validate_provider_expectation(expectation)
    fields = {"schema_version", "connector_id", "auth_method", "setup_version", "client_version"}
    _strict_keys(observed, fields, fields)
    if observed["schema_version"] != 1:
        raise ContractError("observed schema")
    if observed["connector_id"] != state["connector_id"] or observed["connector_id"] != expectation["connector_id"]:
        raise ContractError("connector mismatch")
    if observed["auth_method"] not in ALLOWED_AUTH:
        raise ContractError("observed auth")
    if observed["auth_method"] != state["auth_method"]:
        raise ContractError("observed auth does not match connector state")
    _clean_text(observed["setup_version"], 40)
    observed_client_version = _version_tuple(observed["client_version"])

    issues = []
    if observed["auth_method"] in expectation["deprecated_auth_methods"]:
        issues.append("auth_method_deprecated")
    if observed["auth_method"] != expectation["auth_method"]:
        issues.append("auth_method_migration_required")
    if observed["setup_version"] != expectation["setup_version"]:
        issues.append("setup_version_changed")
    if observed_client_version < _version_tuple(expectation["minimum_client_version"]):
        issues.append("client_version_too_old")
    return {
        "compatible": not issues,
        "issues": issues,
        "requires_user_action": bool(issues),
    }


def apply_provider_compatibility(state: dict, expectation: dict, observed: dict) -> dict:
    """Return the canonical connector state after compatibility is applied fail-closed.

    This is deliberately pure: it never mutates caller-owned state and never performs auth,
    network, secret, or paid-provider actions. A provider incompatibility must be reflected in
    the same state machine that drives Settings and Ready, rather than existing only as a side
    report that callers can accidentally ignore.
    """
    compatibility = evaluate_provider_compatibility(state, expectation, observed)
    result = dict(state)
    if compatibility["compatible"]:
        return result

    issues = compatibility["issues"]
    auth_blocked = any(issue in {"auth_method_deprecated", "auth_method_migration_required"} for issue in issues)
    result["ready"] = False
    result["health"] = "deprecated" if auth_blocked else "setup_required"
    result["issue_code"] = issues[0]
    validate_connector_state(result)
    return result


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
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ContractError("now")
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
    _clean_text(notice["issue_code"], 80)
    _clean_text(notice["remediation_path"], 200)
    if not notice["remediation_path"].startswith("settings://connectors/"):
        raise ContractError("bad remediation")
    issue = state["issue_code"] or "not_ready"
    if notice["notice_fingerprint"] != _fingerprint(state["connector_id"], issue, state["project_id"]):
        return True
    dismiss_until = notice["dismiss_until"]
    if dismiss_until is None:
        return True
    try:
        parsed_dismiss_until = datetime.fromisoformat(dismiss_until)
    except (TypeError, ValueError) as exc:
        raise ContractError("dismiss") from exc
    if parsed_dismiss_until.tzinfo is None:
        raise ContractError("dismiss")
    return now >= parsed_dismiss_until
