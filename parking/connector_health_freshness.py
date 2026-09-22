from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

_MAX_TS = 2**63 - 1
_DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60
_HEALTHY = {"ok", "healthy"}
_AUTH = {"none", "oauth", "api-key", "id", "local"}
_HEALTH = {"ok", "healthy", "degraded", "error", "expired", "auth-expired", "setup-required", "unavailable"}


@dataclass(frozen=True)
class ConnectorHealthEvidence:
    """Secret-free evidence from Captain's connector health monitor."""

    plugin_id: str
    checked_at: int
    health: str
    auth_method: str
    setup_version: int

    def validate(self) -> None:
        _validate_config(self.plugin_id, self.auth_method, self.setup_version)
        _validate_timestamp(self.checked_at, "checked_at")
        if self.health not in _HEALTH:
            raise ValueError("invalid health")


@dataclass(frozen=True)
class ConnectorHealthWatermark:
    """Newest accepted health timestamp, scoped to one secret-free connector config."""

    plugin_id: str
    auth_method: str
    setup_version: int
    checked_at: int

    def validate(self, *, now: int) -> None:
        _validate_config(self.plugin_id, self.auth_method, self.setup_version)
        _validate_timestamp(self.checked_at, "watermark checked_at")
        if self.checked_at > now:
            raise ValueError("health watermark is from future")


def _validate_config(plugin_id: object, auth_method: object, setup_version: object) -> None:
    if not isinstance(plugin_id, str) or not plugin_id or len(plugin_id) > 64:
        raise ValueError("invalid plugin_id")
    if auth_method not in _AUTH:
        raise ValueError("invalid auth_method")
    if isinstance(setup_version, bool) or not isinstance(setup_version, int) or setup_version < 1:
        raise ValueError("invalid setup_version")


def _validate_timestamp(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_TS:
        raise ValueError(f"invalid {field}")


def project_connector_health(
    public_state: Mapping[str, object],
    evidence: ConnectorHealthEvidence | None,
    *,
    now: int,
    max_age_seconds: int = _DEFAULT_MAX_AGE_SECONDS,
    watermark: ConnectorHealthWatermark | None = None,
) -> dict:
    """Fail closed for missing, stale, replayed, future, unhealthy, or mismatched evidence.

    The live Settings registry remains canonical for manifest/auth/permission/setup state.
    Health contributes bounded secret-free evidence only and cannot upgrade a base state
    that is already not Ready. Replay protection is configuration-bound: a watermark from
    a previous auth/setup configuration never blocks fresh evidence for a new configuration,
    while cross-plugin watermark substitution is rejected.
    """
    _validate_timestamp(now, "now")
    if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int) or not 1 <= max_age_seconds <= 7 * 24 * 60 * 60:
        raise ValueError("invalid max_age_seconds")
    if watermark is not None:
        watermark.validate(now=now)

    required = {"id", "kind", "auth_method", "setup_version", "health", "ready", "issues", "next_action"}
    if not required <= set(public_state):
        raise ValueError("incomplete public state")
    if public_state["kind"] != "connector":
        return dict(public_state)

    plugin_id = public_state["id"]
    auth_method = public_state["auth_method"]
    setup_version = public_state["setup_version"]
    _validate_config(plugin_id, auth_method, setup_version)
    base_ready = public_state["ready"]
    base_issues = public_state["issues"]
    if not isinstance(base_ready, bool) or not isinstance(base_issues, list) or not all(isinstance(x, str) for x in base_issues):
        raise ValueError("invalid public readiness state")

    if watermark is not None and watermark.plugin_id != plugin_id:
        raise ValueError("health watermark plugin mismatch")
    watermark_applies = bool(
        watermark is not None
        and watermark.auth_method == auth_method
        and watermark.setup_version == setup_version
    )

    issues = list(base_issues)
    health_issue: str | None = None
    if evidence is None:
        health_issue = "health-check-missing"
    else:
        evidence.validate()
        if evidence.plugin_id != plugin_id:
            raise ValueError("health evidence plugin mismatch")
        if evidence.auth_method != auth_method:
            health_issue = "health-check-auth-method-mismatch"
        elif evidence.setup_version != setup_version:
            health_issue = "health-check-setup-version-mismatch"
        elif evidence.checked_at > now:
            health_issue = "health-check-from-future"
        elif watermark_applies and watermark is not None and evidence.checked_at < watermark.checked_at:
            health_issue = "health-check-replayed"
        elif now - evidence.checked_at > max_age_seconds:
            health_issue = "health-check-stale"
        elif evidence.health not in _HEALTHY:
            health_issue = f"health-{evidence.health}"

    if health_issue is not None and health_issue not in issues:
        issues.append(health_issue)

    projected = dict(public_state)
    projected["health_evidence_checked_at"] = None if evidence is None else evidence.checked_at
    projected["health_evidence_fresh"] = health_issue is None
    projected["issues"] = issues
    projected["ready"] = bool(base_ready and health_issue is None)
    if health_issue is not None and public_state["next_action"] is None:
        projected["next_action"] = "test-connection"
    return projected
