import unittest

from captain_memory_contract import assert_memory_scope, build_memory, promote_to_shared


class MemoryContractTests(unittest.TestCase):
    def test_project_memory_requires_exact_scope(self):
        m = build_memory(memory_id="m1", kind="project_fact", payload={"fact": "x"}, project_id="p1", repo_scope="repo-a")
        assert_memory_scope(m, project_id="p1", repo_scope="repo-a")
        with self.assertRaises(PermissionError):
            assert_memory_scope(m, project_id="p2", repo_scope="repo-a")
        with self.assertRaises(PermissionError):
            assert_memory_scope(m, project_id="p1", repo_scope="repo-b")

    def test_project_memory_missing_scope_fails_closed(self):
        with self.assertRaises(ValueError):
            build_memory(memory_id="m2", kind="project_decision", payload={"decision": "x"})

    def test_shared_learning_cannot_carry_project_scope(self):
        with self.assertRaises(ValueError):
            build_memory(memory_id="m3", kind="shared_learning", payload={"rule": "generic"}, project_id="p1", repo_scope="repo-a")

    def test_forbidden_sensitive_keys_are_rejected(self):
        for key in ("token", "api_key", "authorization", "cookie", "password", "secret", "repo_scope", "chat_id"):
            with self.assertRaises(ValueError, msg=key):
                build_memory(memory_id="m4", kind="shared_learning", payload={key: "nope"})

    def test_path_like_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            build_memory(memory_id="../escape", kind="shared_learning", payload={"rule": "x"})

    def test_payload_is_bounded_and_scalar_only(self):
        with self.assertRaises(ValueError):
            build_memory(memory_id="m5", kind="shared_learning", payload={"blob": "x" * 5000})
        with self.assertRaises(ValueError):
            build_memory(memory_id="m6", kind="shared_learning", payload={"nested": {"x": 1}})

    def test_distillation_is_explicit_not_raw_copy(self):
        m = build_memory(memory_id="m7", kind="project_fact", payload={"raw": "project-specific"}, project_id="p1", repo_scope="repo-a")
        shared = promote_to_shared(m, distilled_payload={"rule": "generic only"})
        self.assertEqual(shared.scope, "global")
        self.assertIsNone(shared.scope_hash)
        self.assertEqual(shared.payload, {"rule": "generic only"})
        self.assertNotIn("raw", shared.payload)

    def test_unknown_memory_kind_rejected(self):
        with self.assertRaises(ValueError):
            build_memory(memory_id="m8", kind="project_magic", payload={"x": 1}, project_id="p1", repo_scope="repo-a")


if __name__ == "__main__":
    unittest.main()
