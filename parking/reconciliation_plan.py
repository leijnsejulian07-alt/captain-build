from __future__ import annotations

import re

from integration.reconciliation_state import validate_state
from integration.source_snapshot import assert_snapshot_unchanged, validate_observed_sources
from integration_manifest import integration_order, validate_manifest

ALLOWED_COMPONENT_STATES = {"pending", "verified", "integrated", "rejected"}
ALLOWED_PR_STATES = {"open", "closed", "merged"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def component_lifecycle_view(reconciliation_state: dict) -> dict[str, str]:
    """Return the planner's minimal lifecycle view from canonical persisted state.

    The canonical state is validated first, including acceptance evidence digests and
    local-base binding. This prevents reconnect code from hand-translating or
    accidentally bypassing the persisted fail-closed reconciliation contract.
    """
    validate_state(reconciliation_state)
    return {
        component_id: row["state"]
        for component_id, row in reconciliation_state["components"].items()
    }


def build_reconciliation_plan(manifest: dict, component_state: dict, pr_state: dict, external_ready: set[str]) -> list[dict]:
    validate_manifest(manifest)
    if not isinstance(component_state, dict) or not isinstance(pr_state, dict) or not isinstance(external_ready, set):
        raise ValueError("invalid reconciliation inputs")
    components = {c["id"]: c for c in manifest["components"]}
    if set(component_state) - set(components):
        raise ValueError("unknown component state")
    if any(v not in ALLOWED_COMPONENT_STATES for v in component_state.values()):
        raise ValueError("invalid component lifecycle state")
    expected_prs = {c["pr"] for c in manifest["components"]}
    if set(pr_state) != expected_prs:
        raise ValueError("PR state set must exactly match manifest components")
    if any(type(k) is not int or v not in ALLOWED_PR_STATES for k, v in pr_state.items()):
        raise ValueError("invalid PR state")
    declared_external = set(manifest.get("external_prerequisites", []))
    if external_ready - declared_external:
        raise ValueError("unknown external prerequisite")

    plan = []
    for component_id in integration_order(manifest):
        c = components[component_id]
        state = component_state.get(component_id, "pending")
        blockers: list[str] = []
        if state in {"integrated", "rejected"}:
            action = "skip"
        else:
            pr = pr_state[c["pr"]]
            if pr != "open":
                blockers.append(f"pr:{c['pr']}:{pr}")
            for dep in c.get("depends_on", []):
                if dep in declared_external:
                    if dep not in external_ready:
                        blockers.append(f"external:{dep}")
                elif component_state.get(dep) != "integrated":
                    blockers.append(f"component:{dep}")
            action = "blocked" if blockers else ("verify" if state == "pending" else "integrate")
        plan.append({"id": component_id, "pr": c["pr"], "state": state, "action": action, "blockers": blockers})
    return plan


def build_reconciliation_plan_from_state(
    manifest: dict,
    reconciliation_state: dict,
    pr_state: dict,
    external_ready: set[str],
) -> list[dict]:
    validate_manifest(manifest)
    validate_state(reconciliation_state)
    local_base_sha = reconciliation_state.get("local_base_sha")
    if not isinstance(local_base_sha, str) or not SHA_RE.fullmatch(local_base_sha):
        raise ValueError("current local base sha must be captured before reconciliation planning")
    manifest_components = {c["id"] for c in manifest["components"]}
    persisted_components = set(reconciliation_state["components"])
    if persisted_components != manifest_components:
        raise ValueError("canonical reconciliation state must exactly match manifest components")
    return build_reconciliation_plan(
        manifest,
        component_lifecycle_view(reconciliation_state),
        pr_state,
        external_ready,
    )


def build_reconciliation_plan_from_snapshot(
    manifest: dict,
    reconciliation_state: dict,
    planned_sources: dict,
    current_sources: dict,
    source_digest: str,
    external_ready: set[str],
) -> list[dict]:
    """Build an actionable plan only while the parked source PR snapshot is unchanged.

    This is the canonical reconnect entry point once live GitHub PR metadata has been
    collected. Head/base drift, PR replacement, closure, or tampered snapshot evidence
    fails closed before any verify/integrate action can be returned.
    """
    assert_snapshot_unchanged(manifest, planned_sources, current_sources, source_digest)
    normalized = validate_observed_sources(manifest, current_sources)
    pr_state = {row["pr"]: row["state"] for row in normalized.values()}
    return build_reconciliation_plan_from_state(
        manifest,
        reconciliation_state,
        pr_state,
        external_ready,
    )


def next_actionable(plan: list[dict]) -> dict | None:
    if not isinstance(plan, list):
        raise ValueError("plan must be a list")
    for row in plan:
        if not isinstance(row, dict) or row.get("action") not in {"verify", "integrate", "blocked", "skip"}:
            raise ValueError("invalid plan row")
        if row["action"] in {"verify", "integrate"}:
            return row
    return None
