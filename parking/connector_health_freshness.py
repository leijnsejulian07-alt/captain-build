from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

_MAX_TS = 2**63 - 1
_DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60
_REMOTE_AUTH = {"oauth", "api-key", "id"}
_HEALTHY = {"ok", "healthy"}


@dataclass(frozen=True)
class ConnectorHealthEvidence:
    """Secret-free evidence from Captain's connector health monitor."""

    plugin_id: str
    checked_at: int
    health: str
    auth_method: str
    setup_version: int

    def validate(self) -> None:
        if not self.plugin_id or len(self.plugin_id) > 64:
            raise ValueError("invalid plugin_id")
        if isinstance(self.checked_at, bool) or not isinstance(self.checked_at, int):
            raise ValueError("invalid checked_at")
        if not 0 <= self.checked_at <= _MAX_TS:
            raise ValueError("invalid checked_at")
        if self.health not in {"ok", "healthy", "degraded", "error", "expired", "auth-expired", "setup-required", "unavailable"}:
            raise ValueError("invalid health")
        if self.auth_method not in {"none", "oauth", "api-key", "id", "local"}:
            raise ValueError("invalid auth_method")
        if isinstance(self.setup_version, bool) or not isinstance(self.setup_version, int) or self.setup_version < 1:
            raise ValueError("invalid setup_version")


def project_connector_health(
    public_state: Mapping[str, object],
    evidence: ConnectorHealthEvidence | None,
    *,
    now: int,
    max_age_seconds: int = _DEFAULT_MAX_AGE_SECONDS,
) -> dict:
    """Fail closed when readiness depends on missing, stale, or mismatched health evidence.

    This is a parking adapter: the live Settings registry remains the canonical source of
    manifest/auth/permission/setup state. The health monitor contributes only bounded,
    secret-free evidence and cannot make an otherwise-not-ready connector Ready.
    """
    if isinstance(now, bool) or not isinstance(now, int) or not 0 <= now <= _MAX_TS:
        raise ValueError("invalid now")
    if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int) or not 1 <= max_age_seconds <= 7 * 24 * 60 * 60:
        raise ValueError("invalid max_age_seconds")

    required = {"id", "kind", "auth_method", "setup_version", "health", "ready", "issues", "next_action"}
    if not required <= set(public_state):
        raise ValueError("incomplete public state")
    if public_state["kind"] != "connector":
        return dict(public_state)

    plugin_id = public_state["id"]
    auth_method = public_state["auth_method"]
    setup_version = public_state["setup_version"]
    base_ready = public_state["ready"]
    base_issues = public_state["issues"]
    if not isinstance(plugin_id, str) or not isinstance(auth_method, str):
        raise ValueError("invalid public state")
    if isinstance(setup_version, bool) or not isinstance(setup_version, int) or setup_version < 1:
        raise ValueError("invalid public setup_version")
    if not isinstance(base_ready, bool) or not isinstance(base_issues, list) or not all(isinstance(x, str) for x in base_issues):
        raise ValueError("invalid public readiness state")

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
