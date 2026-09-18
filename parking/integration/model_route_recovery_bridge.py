from __future__ import annotations

from datetime import datetime
from typing import Mapping

from connector_health_runtime import apply_connection_probe
from connector_notice_runtime import ConnectorNoticeStore
from connector_settings_contract import ContractError
from model_route_failure_policy import (
    RouteFailurePolicyError,
    clear_route_failure_after_success,
    parse_failure_state,
)


_RECOVERABLE_BLOCKING_FAILURES = {
    "auth_invalid",
    "permission_denied",
    "setup_required",
}


def recover_route_after_test_connection(
    state: dict,
    failure_state: Mapping[str, object],
    *,
    request: dict,
    probe: dict,
    notice_store: ConnectorNoticeStore,
    remediation_path: str,
    now: datetime,
) -> tuple[dict, dict]:
    """Authorize deletion of one exact route failure after an explicit successful Test Connection.

    This is the fail-closed recovery counterpart to model_route_connector_bridge. It does not
    delete router state itself: the owning route-failure store may delete only the exact
    provider/model key named by the returned receipt, after this function succeeds.

    A generic Test Connection may recover auth/permission/setup blocks because those checks are
    explicitly part of connector_health_runtime's request contract. It may NOT clear a provider
    deprecation (which needs a migration/version-specific remedy) or a transient/model rate-limit
    cooldown (which expires under the routing policy or needs a model-call success).
    """
    if not isinstance(notice_store, ConnectorNoticeStore):
        raise ContractError("notice store")
    try:
        failure = parse_failure_state(failure_state)
    except RouteFailurePolicyError as exc:
        raise ContractError("invalid route failure") from exc

    if state.get("connector_id") != failure.provider_id:
        raise ContractError("provider connector mismatch")
    if failure.failure_kind not in _RECOVERABLE_BLOCKING_FAILURES:
        raise ContractError("route failure requires different recovery evidence")

    recovered = apply_connection_probe(state, probe, now, request=request)
    if recovered["health"] != "healthy" or recovered["ready"] is not True:
        raise ContractError("test connection did not restore ready healthy state")

    try:
        observed_at = datetime.fromisoformat(probe["observed_at"])
    except (TypeError, ValueError) as exc:
        raise ContractError("probe observed_at") from exc
    if observed_at.tzinfo is None:
        raise ContractError("probe observed_at")
    observed_at_ms = int(observed_at.timestamp() * 1000)

    try:
        clear_route_failure_after_success(
            failure_state,
            provider_id=failure.provider_id,
            model_id=failure.model_id,
            observed_at_ms=observed_at_ms,
        )
    except RouteFailurePolicyError as exc:
        raise ContractError("route recovery evidence rejected") from exc

    # A recovered connector automatically removes its persisted unresolved notice. evaluate()
    # returns None for ready connectors and clears the digest-only row.
    notice = notice_store.evaluate(recovered, remediation_path, now)
    if notice is not None:
        raise ContractError("resolved connector produced remediation notice")

    return recovered, {
        "schema_version": 1,
        "provider_id": failure.provider_id,
        "model_id": failure.model_id,
        "failure_kind": failure.failure_kind,
        "clear_authorized": True,
        "observed_at_ms": observed_at_ms,
        "secret_fields": [],
    }
