import json
import unittest
from pathlib import Path

from integration.external_prerequisites import create_verified_prerequisite
from integration.reconciliation_state import set_local_base
from integration.source_snapshot import source_snapshot_digest
from reconciliation_plan import build_reconciliation_plan_from_evidence_snapshot

HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / "integration-manifest.json").read_text(encoding="utf-8"))
BASE_SHA = "a" * 40
PREREQUISITE = "local-openbuilder-bridge"


def canonical_state() -> dict:
    state = {
        "schema_version": 3,
        "local_base_sha": None,
        "components": {c["id"]: {"state": "pending"} for c in MANIFEST["components"]},
    }
    return set_local_base(state, BASE_SHA)


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


class EvidenceBoundPlannerTests(unittest.TestCase):
    def build(self, evidence: dict):
        planned = source_snapshot()
        return build_reconciliation_plan_from_evidence_snapshot(
            MANIFEST,
            canonical_state(),
            planned,
            {key: dict(value) for key, value in planned.items()},
            source_snapshot_digest(MANIFEST, planned),
            evidence,
        )

    def test_verified_external_evidence_unlocks_dependency(self):
        evidence = {
            PREREQUISITE: create_verified_prerequisite(
                PREREQUISITE, BASE_SHA, "openbuilder-local-doctor"
            )
        }
        plan = self.build(evidence)
        preview = next(row for row in plan if row["id"] == "preview-session")
        self.assertNotIn(f"external:{PREREQUISITE}", preview["blockers"])

    def test_missing_external_evidence_remains_blocked(self):
        plan = self.build({})
        preview = next(row for row in plan if row["id"] == "preview-session")
        self.assertIn(f"external:{PREREQUISITE}", preview["blockers"])

    def test_stale_external_evidence_fails_closed(self):
        evidence = {
            PREREQUISITE: create_verified_prerequisite(
                PREREQUISITE, "b" * 40, "openbuilder-local-doctor"
            )
        }
        with self.assertRaisesRegex(ValueError, "stale"):
            self.build(evidence)

    def test_tampered_external_evidence_fails_closed(self):
        evidence = {
            PREREQUISITE: create_verified_prerequisite(
                PREREQUISITE, BASE_SHA, "openbuilder-local-doctor"
            )
        }
        evidence[PREREQUISITE]["evidence_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "modified"):
            self.build(evidence)


if __name__ == "__main__":
    unittest.main()
