from __future__ import annotations

from integration_manifest import integration_order, validate_manifest

ALLOWED_COMPONENT_STATES = {"pending", "verified", "integrated", "rejected"}
ALLOWED_PR_STATES = {"open", "closed", "merged"}


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


def next_actionable(plan: list[dict]) -> dict | None:
    if not isinstance(plan, list):
        raise ValueError("plan must be a list")
    for row in plan:
        if not isinstance(row, dict) or row.get("action") not in {"verify", "integrate", "blocked", "skip"}:
            raise ValueError("invalid plan row")
        if row["action"] in {"verify", "integrate"}:
            return row
    return None
