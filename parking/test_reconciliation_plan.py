import json
import unittest
from pathlib import Path

from reconciliation_plan import build_reconciliation_plan, next_actionable

HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / "integration-manifest.json").read_text(encoding="utf-8"))
OPEN = {c["pr"]: "open" for c in MANIFEST["components"]}


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


if __name__ == "__main__":
    unittest.main()
