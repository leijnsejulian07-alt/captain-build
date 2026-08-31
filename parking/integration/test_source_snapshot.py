import copy
import unittest

from source_snapshot import assert_snapshot_unchanged, source_snapshot_digest, validate_observed_sources


MANIFEST = {
    "schema_version": 1,
    "required_local_checks": ["unit", "doctor", "router", "project_isolation", "repo_isolation"],
    "external_prerequisites": [],
    "components": [
        {"id": "agent-skills", "pr": 1, "depends_on": []},
        {"id": "scoped-jobs", "pr": 2, "depends_on": []},
    ],
}
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
SHA_D = "d" * 40


def observed():
    return {
        "agent-skills": {"pr": 1, "state": "open", "head_sha": SHA_A, "base_sha": SHA_C},
        "scoped-jobs": {"pr": 2, "state": "open", "head_sha": SHA_B, "base_sha": SHA_C},
    }


class SourceSnapshotTests(unittest.TestCase):
    def test_valid_snapshot_is_stable_and_accepted(self):
        rows = observed()
        digest = source_snapshot_digest(MANIFEST, rows)
        self.assertEqual(digest, source_snapshot_digest(MANIFEST, rows))
        assert_snapshot_unchanged(MANIFEST, rows, rows, digest)

    def test_head_sha_change_fails_closed(self):
        planned = observed()
        current = observed()
        current["agent-skills"]["head_sha"] = SHA_D
        with self.assertRaises(ValueError):
            assert_snapshot_unchanged(MANIFEST, planned, current, source_snapshot_digest(MANIFEST, planned))

    def test_base_sha_change_fails_closed(self):
        planned = observed()
        current = observed()
        current["scoped-jobs"]["base_sha"] = SHA_D
        with self.assertRaises(ValueError):
            assert_snapshot_unchanged(MANIFEST, planned, current, source_snapshot_digest(MANIFEST, planned))

    def test_closed_pr_fails_closed(self):
        rows = observed()
        digest = source_snapshot_digest(MANIFEST, rows)
        current = observed()
        current["agent-skills"]["state"] = "closed"
        with self.assertRaises(ValueError):
            assert_snapshot_unchanged(MANIFEST, rows, current, digest)

    def test_missing_or_extra_component_fails_closed(self):
        rows = observed()
        del rows["agent-skills"]
        with self.assertRaises(ValueError):
            validate_observed_sources(MANIFEST, rows)
        rows = observed()
        rows["extra"] = {"pr": 3, "state": "open", "head_sha": SHA_D, "base_sha": SHA_C}
        with self.assertRaises(ValueError):
            validate_observed_sources(MANIFEST, rows)

    def test_pr_substitution_fails_closed(self):
        rows = observed()
        rows["agent-skills"]["pr"] = 999
        with self.assertRaises(ValueError):
            validate_observed_sources(MANIFEST, rows)

    def test_bad_sha_and_unknown_fields_fail_closed(self):
        rows = observed()
        rows["agent-skills"]["head_sha"] = "not-a-sha"
        with self.assertRaises(ValueError):
            validate_observed_sources(MANIFEST, rows)
        rows = observed()
        rows["agent-skills"]["url"] = "https://example.invalid"
        with self.assertRaises(ValueError):
            validate_observed_sources(MANIFEST, rows)

    def test_tampered_expected_digest_fails_closed(self):
        rows = observed()
        with self.assertRaises(ValueError):
            assert_snapshot_unchanged(MANIFEST, rows, rows, "0" * 64)

    def test_dependency_graph_change_invalidates_snapshot(self):
        rows = observed()
        digest = source_snapshot_digest(MANIFEST, rows)
        changed = copy.deepcopy(MANIFEST)
        changed["components"][1]["depends_on"] = ["agent-skills"]
        self.assertNotEqual(digest, source_snapshot_digest(changed, rows))
        with self.assertRaises(ValueError):
            assert_snapshot_unchanged(changed, rows, rows, digest)

    def test_acceptance_or_external_prerequisite_change_invalidates_snapshot(self):
        rows = observed()
        digest = source_snapshot_digest(MANIFEST, rows)
        changed = copy.deepcopy(MANIFEST)
        changed["external_prerequisites"] = ["openbuilder-local"]
        self.assertNotEqual(digest, source_snapshot_digest(changed, rows))


if __name__ == "__main__":
    unittest.main()
