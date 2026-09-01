from __future__ import annotations

from typing import Mapping

from connector_health_freshness import (
    ConnectorHealthEvidence,
    ConnectorHealthWatermark,
    project_connector_health,
)

_DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60


def advance_health_watermark(
    public_state: Mapping[str, object],
    evidence: ConnectorHealthEvidence | None,
    *,
    now: int,
    previous: ConnectorHealthWatermark | None = None,
    max_age_seconds: int = _DEFAULT_MAX_AGE_SECONDS,
) -> ConnectorHealthWatermark | None:
    """Return the watermark that may be persisted after one health-check transaction.

    The caller must persist the returned value in the same transaction as accepting the
    health-check result. Failed, stale, future, replayed, unhealthy, plugin-mismatched,
    auth-mismatched, or setup-mismatched evidence can never advance the replay boundary.

    Readiness is intentionally not required here: a healthy connector check may be valid
    evidence even while Captain separately keeps the plugin not Ready because permissions,
    enablement, or another Settings gate is unresolved. This helper only governs health
    evidence replay state and never upgrades canonical Settings readiness.
    """
    if public_state.get("kind") != "connector":
        raise ValueError("health watermark requires connector state")

    projected = project_connector_health(
        public_state,
        evidence,
        now=now,
        max_age_seconds=max_age_seconds,
        watermark=previous,
    )

    if evidence is None or projected.get("health_evidence_fresh") is not True:
        return previous

    return ConnectorHealthWatermark(
        plugin_id=evidence.plugin_id,
        auth_method=evidence.auth_method,
        setup_version=evidence.setup_version,
        checked_at=evidence.checked_at,
    )
