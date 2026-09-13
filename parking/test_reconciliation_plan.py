import json
import unittest
from pathlib import Path

from integration.reconciliation_state import set_local_base, transition
from integration.source_snapshot import source_snapshot_digest
from reconciliation_plan import (
    build_reconciliation_plan,
    build_reconciliation_plan_from_snapshot,
    build_reconciliation_plan_from_state,
    component_lifecycle_view,
    next_actionable,
)

HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / "integration-manifest.json").read_text(encoding="utf-8"))
OPEN = {c["pr"]: "open" for c in MANIFEST["components"]}
CHECKS = {
    "unit": "passed",
    "doctor": "passed",
    "router": "passed",
    "project_isolation": "passed",
    "repo_isolation": "passed",
}
BASE_SHA = "a" * 40


def canonical_state() -> dict:
    return {
        "schema_version": 3,
        "local_base_sha": None,
        "components": {c["id"]: {"state": "pending"} for c in MANIFEST["components"]},
    }


def source_snapshot() -> dict:
    return {
        c["id"]: {
            "pr": c["pr"],
            "state": "open",
            "repository": MANIFEST["source_repository"],
            "head_ref": f"parking/component-{c['pr']}",
            "base_ref": "main",
            "head_sha": format(c["pr"], "040x")[-40:],
            "base_sha": "f" * 40,
        }
        for c in MANIFEST["components"]
    }


class ReconciliationPlanTests(unittest.TestCase):
    def test_root_component_is_actionable(self):
        plan = build_reconciliation_plan(MANIFEST, {}, OPEN, set())
        self.assertEqual(next_actionable(plan)["action"], "verify")

    def test_dependency_blocks_until_integrated(self):
        plan = build_reconciliation_plan(MANIFEST, {"scoped-jobs": "verified"}, OPEN, set())
        row = next(x for x in plan if x["id"] == "bounded-build-profiles")
        self.assertEqual(row["action"], "blocked")
        self.assertIn("component:scoped-jobs", row["blockers"])

    def test_verified_dependency_unlocks_only_after_integration(self):
        state = {"scoped-jobs": "integrated"}
        plan = build_reconciliation_plan(MANIFEST, state, OPEN, set())
        row = next(x for x in plan if x["id"] == "bounded-build-profiles")
        self.assertEqual(row["action"], "verify")

    def test_external_prerequisite_is_fail_closed(self):
        plan = build_reconciliation_plan(MANIFEST, {}, OPEN, set())
        row = next(x for x in plan if x["id"] == "preview-session")
        self.assertEqual(row["action"], "blocked")
        self.assertIn("external:local-openbuilder-bridge", row["blockers"])

    def test_closed_pr_is_not_actionable(self):
        prs = dict(OPEN)
        prs[1] = "closed"
        plan = build_reconciliation_plan(MANIFEST, {}, prs, set())
        row = next(x for x in plan if x["id"] == "agent-skills")
        self.assertEqual(row["action"], "blocked")

    def test_integrated_or_rejected_are_terminal_skips(self):
        state = {"agent-skills": "integrated", "scoped-jobs": "rejected"}
        plan = build_reconciliation_plan(MANIFEST, state, OPEN, set())
        actions = {x["id"]: x["action"] for x in plan}
        self.assertEqual(actions["agent-skills"], "skip")
        self.assertEqual(actions["scoped-jobs"], "skip")

    def test_unknown_component_state_fails_closed(self):
        with self.assertRaises(ValueError):
            build_reconciliation_plan(MANIFEST, {"not-real": "verified"}, OPEN, set())

    def test_unknown_external_ready_fails_closed(self):
        with self.assertRaises(ValueError):
            build_reconciliation_plan(MANIFEST, {}, OPEN, {"not-real"})

    def test_missing_pr_state_fails_closed(self):
        prs = dict(OPEN)
        prs.pop(next(iter(prs)))
        with self.assertRaises(ValueError):
            build_reconciliation_plan(MANIFEST, {}, prs, set())

    def test_extra_pr_state_fails_closed(self):
        prs = dict(OPEN)
        prs[999999] = "open"
        with self.assertRaises(ValueError):
            build_reconciliation_plan(MANIFEST, {}, prs, set())

    def test_canonical_state_requires_captured_local_base_before_planning(self):
        state = canonical_state()
        with self.assertRaisesRegex(ValueError, "local base sha"):
            build_reconciliation_plan_from_state(MANIFEST, state, OPEN, set())

    def test_canonical_state_must_exactly_match_manifest_components(self):
        state = set_local_base(canonical_state(), BASE_SHA)
        state["components"].pop(next(iter(state["components"])))
        with self.assertRaisesRegex(ValueError, "exactly match manifest components"):
            build_reconciliation_plan_from_state(MANIFEST, state, OPEN, set())

    def test_canonical_state_drives_planner_without_manual_translation(self):
        state = set_local_base(canonical_state(), BASE_SHA)
        state = transition(state, "scoped-jobs", "verified", CHECKS)
        plan = build_reconciliation_plan_from_state(MANIFEST, state, OPEN, set())
        row = next(x for x in plan if x["id"] == "scoped-jobs")
        self.assertEqual(row["action"], "integrate")

    def test_tampered_canonical_evidence_fails_closed_before_planning(self):
        state = set_local_base(canonical_state(), BASE_SHA)
        state = transition(state, "scoped-jobs", "verified", CHECKS)
        state["components"]["scoped-jobs"]["evidence_digest"] = "0" * 64
        with self.assertRaises(ValueError):
            component_lifecycle_view(state)

    def test_stale_canonical_base_fails_closed_before_planning(self):
        state = set_local_base(canonical_state(), BASE_SHA)
        state = transition(state, "scoped-jobs", "verified", CHECKS)
        state["local_base_sha"] = "b" * 40
        with self.assertRaises(ValueError):
            build_reconciliation_plan_from_state(MANIFEST, state, OPEN, set())

    def test_snapshot_bound_planner_accepts_unchanged_sources(self):
        state = set_local_base(canonical_state(), BASE_SHA)
        planned = source_snapshot()
        digest = source_snapshot_digest(MANIFEST, planned)
        current = {k: dict(v) for k, v in planned.items()}
        plan = build_reconciliation_plan_from_snapshot(MANIFEST, state, planned, current, digest, set())
        self.assertEqual(next_actionable(plan)["action"], "verify")

    def test_snapshot_bound_planner_rejects_head_drift(self):
        state = set_local_base(canonical_state(), BASE_SHA)
        planned = source_snapshot()
        current = {k: dict(v) for k, v in planned.items()}
        current[next(iter(current))]["head_sha"] = "e" * 40
        digest = source_snapshot_digest(MANIFEST, planned)
        with self.assertRaisesRegex(ValueError, "changed after reconciliation planning"):
            build_reconciliation_plan_from_snapshot(MANIFEST, state, planned, current, digest, set())

    def test_snapshot_bound_planner_rejects_closed_source(self):
        state = set_local_base(canonical_state(), BASE_SHA)
        planned = source_snapshot()
        current = {k: dict(v) for k, v in planned.items()}
        current[next(iter(current))]["state"] = "closed"
        digest = source_snapshot_digest(MANIFEST, planned)
        with self.assertRaises(ValueError):
            build_reconciliation_plan_from_snapshot(MANIFEST, state, planned, current, digest, set())


if __name__ == "__main__":
    unittest.main()
