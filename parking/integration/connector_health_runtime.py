from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json

from connector_settings_contract import ContractError, validate_connector_state

ALLOWED_AUTH_STATUS = {"valid", "invalid", "expired", "not_applicable"}
ALLOWED_PROVIDER_STATUS = {"reachable", "degraded", "unreachable"}
MAX_CLOCK_SKEW = timedelta(minutes=5)
DEFAULT_MAX_PROBE_AGE = timedelta(hours=24)


def _strict_keys(value: dict, allowed: set[str], required: set[str]) -> None:
    if not isinstance(value, dict):
        raise ContractError("object required")
    if set(value) - allowed:
        raise ContractError("unknown fields")
    if not required <= set(value):
        raise ContractError("missing fields")


def _clean_text(value: object, max_len: int = 120) -> str:
    if not isinstance(value, str) or not value or len(value) > max_len or value.strip() != value:
        raise ContractError("invalid text")
    return value


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ContractError(field)
    return value


def _probe_digest(connector_id: str, project_id: str, requested_at: datetime) -> str:
    raw = json.dumps(
        [connector_id, project_id, requested_at.isoformat()],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def build_test_connection_request(state: dict, requested_at: datetime) -> dict:
    """Build a metadata-only explicit Test Connection request.

    This never performs OAuth, reads a secret, invents credentials, or activates a provider.
    A provider adapter may execute the returned checks only after the user explicitly invokes
    Test Connection in Captain Settings.
    """
    validate_connector_state(state)
    requested_at = _aware(requested_at, "requested_at")
    if not state["installed"]:
        raise ContractError("connector not installed")
    return {
        "schema_version": 1,
        "connector_id": state["connector_id"],
        "project_id": state["project_id"],
        "auth_method": state["auth_method"],
        "requested_at": requested_at.isoformat(),
        "request_digest": _probe_digest(
            state["connector_id"], state["project_id"], requested_at
        ),
        "checks": ["provider_reachability", "auth_validity", "permissions"],
        "explicit_user_action_required": True,
        "allow_paid_activation": False,
        "secret_fields": [],
    }


def validate_test_connection_request(request: dict) -> bool:
    fields = {
        "schema_version",
        "connector_id",
        "project_id",
        "auth_method",
        "requested_at",
        "request_digest",
        "checks",
        "explicit_user_action_required",
        "allow_paid_activation",
        "secret_fields",
    }
    _strict_keys(request, fields, fields)
    if request["schema_version"] != 1:
        raise ContractError("request schema")
    _clean_text(request["connector_id"], 80)
    _clean_text(request["project_id"], 80)
    _clean_text(request["auth_method"], 40)
    try:
        requested_at = datetime.fromisoformat(request["requested_at"])
    except (TypeError, ValueError) as exc:
        raise ContractError("requested_at") from exc
    if requested_at.tzinfo is None:
        raise ContractError("requested_at")
    expected_digest = _probe_digest(
        request["connector_id"], request["project_id"], requested_at
    )
    if request["request_digest"] != expected_digest:
        raise ContractError("request digest")
    if request["checks"] != ["provider_reachability", "auth_validity", "permissions"]:
        raise ContractError("request checks")
    if request["explicit_user_action_required"] is not True:
        raise ContractError("explicit action")
    if request["allow_paid_activation"] is not False:
        raise ContractError("paid activation")
    if request["secret_fields"] != []:
        raise ContractError("request contains secret fields")
    return True


def validate_connection_probe(probe: dict) -> bool:
    fields = {
        "schema_version",
        "connector_id",
        "project_id",
        "auth_method",
        "observed_at",
        "provider_status",
        "auth_status",
        "permissions_granted",
        "request_digest",
        "secret_fields",
    }
    _strict_keys(probe, fields, fields)
    if probe["schema_version"] != 1:
        raise ContractError("probe schema")
    _clean_text(probe["connector_id"], 80)
    _clean_text(probe["project_id"], 80)
    _clean_text(probe["auth_method"], 40)
    try:
        observed_at = datetime.fromisoformat(probe["observed_at"])
    except (TypeError, ValueError) as exc:
        raise ContractError("observed_at") from exc
    if observed_at.tzinfo is None:
        raise ContractError("observed_at")
    if probe["provider_status"] not in ALLOWED_PROVIDER_STATUS:
        raise ContractError("provider status")
    if probe["auth_status"] not in ALLOWED_AUTH_STATUS:
        raise ContractError("auth status")
    permissions = probe["permissions_granted"]
    if (
        not isinstance(permissions, list)
        or len(permissions) > 32
        or len(permissions) != len(set(permissions))
        or any(not isinstance(permission, str) or not permission for permission in permissions)
    ):
        raise ContractError("permissions")
    _clean_text(probe["request_digest"], 64)
    if len(probe["request_digest"]) != 64 or any(
        char not in "0123456789abcdef" for char in probe["request_digest"]
    ):
        raise ContractError("request digest")
    if probe["secret_fields"] != []:
        raise ContractError("probe contains secret fields")
    return True


def apply_connection_probe(
    state: dict,
    probe: dict,
    now: datetime,
    *,
    request: dict,
    max_probe_age: timedelta = DEFAULT_MAX_PROBE_AGE,
) -> dict:
    """Apply a Test Connection result to canonical Settings state, fail-closed.

    The probe may make Ready false or restore health after an explicit successful test, but it
    never silently changes Installed, Connected, Enabled, auth method, or required permissions.
    """
    validate_connector_state(state)
    validate_test_connection_request(request)
    validate_connection_probe(probe)
    now = _aware(now, "now")
    if not isinstance(max_probe_age, timedelta) or max_probe_age <= timedelta(0):
        raise ContractError("max probe age")
    if request["connector_id"] != state["connector_id"] or request["project_id"] != state["project_id"]:
        raise ContractError("request scope mismatch")
    if request["auth_method"] != state["auth_method"]:
        raise ContractError("request auth mismatch")
    if probe["connector_id"] != state["connector_id"] or probe["project_id"] != state["project_id"]:
        raise ContractError("probe scope mismatch")
    if probe["auth_method"] != state["auth_method"]:
        raise ContractError("probe auth mismatch")
    if probe["request_digest"] != request["request_digest"]:
        raise ContractError("probe request mismatch")

    requested_at = datetime.fromisoformat(request["requested_at"])
    if requested_at > now + MAX_CLOCK_SKEW:
        raise ContractError("request from future")
    if now - requested_at > max_probe_age:
        raise ContractError("request stale")

    observed_at = datetime.fromisoformat(probe["observed_at"])
    if observed_at > now + MAX_CLOCK_SKEW:
        raise ContractError("probe from future")

    result = dict(state)
    result["permissions_granted"] = list(probe["permissions_granted"])

    if now - observed_at > max_probe_age:
        result.update(ready=False, health="degraded", issue_code="connection_test_stale")
    elif probe["auth_status"] == "expired":
        result.update(ready=False, health="expired_auth", issue_code="reauth_required")
    elif probe["auth_status"] == "invalid":
        result.update(ready=False, health="invalid_auth", issue_code="credentials_invalid")
    elif probe["provider_status"] == "unreachable":
        result.update(ready=False, health="degraded", issue_code="provider_unreachable")
    elif probe["provider_status"] == "degraded":
        result.update(ready=False, health="degraded", issue_code="provider_degraded")
    elif not set(result["permissions_required"]) <= set(result["permissions_granted"]):
        result.update(ready=False, health="setup_required", issue_code="permissions_missing")
    elif not result["connected"]:
        result.update(ready=False, health="setup_required", issue_code="connect_required")
    else:
        result["health"] = "healthy"
        result["issue_code"] = None
        result["ready"] = bool(result["installed"] and result["connected"] and result["enabled"])

    validate_connector_state(result)
    return result


def connector_status_view(state: dict) -> dict:
    """Return the secret-free canonical Settings status projection."""
    validate_connector_state(state)
    granted = set(state["permissions_granted"])
    required = set(state["permissions_required"])
    return {
        "schema_version": 1,
        "connector_id": state["connector_id"],
        "project_id": state["project_id"],
        "installed": state["installed"],
        "connected": state["connected"],
        "enabled": state["enabled"],
        "ready": state["ready"],
        "health": state["health"],
        "auth_method": state["auth_method"],
        "permissions": {
            "required": sorted(required),
            "granted": sorted(granted),
            "missing": sorted(required - granted),
        },
        "issue_code": state["issue_code"],
        "secret_fields": [],
    }
