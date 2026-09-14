from __future__ import annotations

from datetime import datetime
from typing import Mapping

from connector_notice_runtime import ConnectorNoticeStore
from connector_settings_contract import ContractError, validate_connector_state
from model_route_failure_policy import RouteFailurePolicyError, parse_failure_state


_FAILURE_TO_CONNECTOR = {
    "transient": ("degraded", "provider_temporarily_unavailable"),
    "rate_limited": ("degraded", "provider_rate_limited"),
    "auth_invalid": ("invalid_auth", "credentials_invalid"),
    "permission_denied": ("setup_required", "permissions_denied"),
    "setup_required": ("setup_required", "provider_setup_required"),
    "provider_deprecated": ("deprecated", "provider_deprecated"),
}


def apply_route_failure_to_connector(state: dict, failure_state: Mapping[str, object]) -> dict:
    """Project a secret-free model-route failure into Captain's canonical connector state.

    The connector/provider identity must match exactly. This function never changes Installed,
    Connected, Enabled, auth method, permissions, or any credential material. It can only make
    Ready false through the canonical connector health state. Recovery is intentionally not
    implemented here: blocked auth/setup/deprecation state must be cleared by Captain's explicit
    successful health/Test Connection flow rather than a router-side guess.
    """
    validate_connector_state(state)
    try:
        failure = parse_failure_state(failure_state)
    except RouteFailurePolicyError as exc:
        raise ContractError("invalid route failure") from exc

    if state["connector_id"] != failure.provider_id:
        raise ContractError("provider connector mismatch")
    if not state["installed"]:
        raise ContractError("route failure for uninstalled connector")

    health, issue_code = _FAILURE_TO_CONNECTOR[failure.failure_kind]
    result = dict(state)
    result["ready"] = False
    result["health"] = health
    result["issue_code"] = issue_code
    validate_connector_state(result)
    return result


def apply_route_failure_and_notice(
    state: dict,
    failure_state: Mapping[str, object],
    *,
    notice_store: ConnectorNoticeStore,
    remediation_path: str,
    now: datetime,
) -> tuple[dict, dict | None]:
    """Atomically derive canonical Settings state and its persistent remediation notice.

    Caller-owned state is never mutated. ConnectorNoticeStore persists only digests/timestamps;
    the surfaced notice is the existing metadata-only canonical notice payload.
    """
    if not isinstance(notice_store, ConnectorNoticeStore):
        raise ContractError("notice store")
    projected = apply_route_failure_to_connector(state, failure_state)
    notice = notice_store.evaluate(projected, remediation_path, now)
    return projected, notice
