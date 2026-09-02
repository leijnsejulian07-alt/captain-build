import copy
import unittest

from candidate_handoff import create_handoff, verify_handoff

A = "a" * 40
B = "b" * 40
T = "c" * 40
M = "d" * 64
D = "e" * 64


def make():
    return create_handoff(
        repository="leijnsejulian07-alt/captain-build",
        source_ref="automation/parking-integration-manifest-20260830",
        head_sha=A,
        head_tree_sha=T,
        base_sha=B,
        manifest_digest=M,
        repo_scope=r"C:\Captain",
        artifacts=[{"path": "parking/integration/source_snapshot.py", "sha256": D, "size": 42}],
    )


def verify(handoff):
    return verify_handoff(
        handoff,
        expected_repository="leijnsejulian07-alt/captain-build",
        expected_source_ref="automation/parking-integration-manifest-20260830",
        expected_head_sha=A,
        expected_head_tree_sha=T,
        expected_base_sha=B,
        expected_manifest_digest=M,
        repo_scope=r"C:\Captain",
    )


class CandidateHandoffTests(unittest.TestCase):
    def test_valid_handoff_exposes_only_safe_summary(self):
        out = verify(make())
        self.assertEqual(out["artifact_count"], 1)
        self.assertNotIn("repo_scope_hash", out)

    def test_cross_repository_is_denied(self):
        with self.assertRaisesRegex(ValueError, "repository mismatch"):
            verify_handoff(
                make(),
                expected_repository="other/project",
                expected_source_ref="automation/parking-integration-manifest-20260830",
                expected_head_sha=A,
                expected_head_tree_sha=T,
                expected_base_sha=B,
                expected_manifest_digest=M,
                repo_scope=r"C:\Captain",
            )

    def test_cross_scope_is_denied(self):
        with self.assertRaisesRegex(ValueError, "repo_scope_hash mismatch"):
            verify_handoff(
                make(),
                expected_repository="leijnsejulian07-alt/captain-build",
                expected_source_ref="automation/parking-integration-manifest-20260830",
                expected_head_sha=A,
                expected_head_tree_sha=T,
                expected_base_sha=B,
                expected_manifest_digest=M,
                repo_scope=r"C:\Other",
            )

    def test_stale_head_tree_base_or_manifest_is_denied(self):
        kwargs = dict(
            expected_repository="leijnsejulian07-alt/captain-build",
            expected_source_ref="automation/parking-integration-manifest-20260830",
            expected_head_sha=A,
            expected_head_tree_sha=T,
            expected_base_sha=B,
            expected_manifest_digest=M,
            repo_scope=r"C:\Captain",
        )
        for key, value in [
            ("expected_head_sha", "f" * 40),
            ("expected_head_tree_sha", "f" * 40),
            ("expected_base_sha", "f" * 40),
            ("expected_manifest_digest", "f" * 64),
        ]:
            bad = dict(kwargs)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify_handoff(make(), **bad)

    def test_artifact_tamper_is_denied(self):
        handoff = make()
        handoff["artifacts"][0]["size"] = 43
        with self.assertRaisesRegex(ValueError, "modified"):
            verify(handoff)

    def test_unknown_handoff_field_is_denied(self):
        handoff = make()
        handoff["surprise"] = True
        with self.assertRaisesRegex(ValueError, "schema"):
            verify(handoff)

    def test_duplicate_or_escaping_artifacts_are_denied(self):
        base = [{"path": "a/b.py", "sha256": D, "size": 1}]
        bad_artifacts = [
            base + copy.deepcopy(base),
            [{"path": "../evil", "sha256": D, "size": 1}],
            [{"path": "/absolute", "sha256": D, "size": 1}],
            [{"path": "a\\b", "sha256": D, "size": 1}],
        ]
        for artifacts in bad_artifacts:
            with self.subTest(artifacts=artifacts), self.assertRaises(ValueError):
                create_handoff(
                    repository="a/b",
                    source_ref="safe/ref",
                    head_sha=A,
                    head_tree_sha=T,
                    base_sha=B,
                    manifest_digest=M,
                    repo_scope="/safe",
                    artifacts=artifacts,
                )

    def test_bool_size_is_denied(self):
        with self.assertRaisesRegex(ValueError, "artifact size"):
            create_handoff(
                repository="a/b",
                source_ref="safe/ref",
                head_sha=A,
                head_tree_sha=T,
                base_sha=B,
                manifest_digest=M,
                repo_scope="/safe",
                artifacts=[{"path": "a", "sha256": D, "size": True}],
            )


if __name__ == "__main__":
    unittest.main()
