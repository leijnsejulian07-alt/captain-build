import copy
import unittest

from parking.integration.scope_contract import (
    ScopeKey,
    assert_same_scope,
    bind_resource,
    parse_scope,
    validate_resource_binding,
)


class ScopeContractTests(unittest.TestCase):
    def setUp(self):
        self.scope = {
            "chat_id": "chat-123",
            "project_id": "project-alpha",
            "repo_scope": "leijnsejulian07-alt/example#refs/heads/main",
        }

    def test_exact_scope_matches(self):
        parsed = assert_same_scope(self.scope, dict(self.scope))
        self.assertEqual(parsed, ScopeKey(**self.scope))

    def test_each_scope_axis_fails_closed(self):
        for key, replacement in (
            ("chat_id", "chat-999"),
            ("project_id", "project-beta"),
            ("repo_scope", "leijnsejulian07-alt/other#refs/heads/main"),
        ):
            with self.subTest(key=key):
                other = dict(self.scope)
                other[key] = replacement
                with self.assertRaises(PermissionError):
                    assert_same_scope(self.scope, other)

    def test_scope_rejects_unknown_fields_and_unsafe_repo_scope(self):
        extra = dict(self.scope, token="secret")
        with self.assertRaises(ValueError):
            parse_scope(extra)
        unsafe = dict(self.scope, repo_scope="owner/repo#../../outside")
        with self.assertRaises(ValueError):
            parse_scope(unsafe)

    def test_resource_binding_round_trip(self):
        binding = bind_resource(self.scope, resource_kind="preview_session", resource_id="preview-1")
        validated = validate_resource_binding(binding, self.scope, resource_kind="preview_session")
        self.assertEqual(validated, binding)

    def test_cross_project_resource_reuse_is_rejected(self):
        binding = bind_resource(self.scope, resource_kind="builder_session", resource_id="builder-1")
        other_scope = dict(self.scope, project_id="project-beta")
        with self.assertRaises(PermissionError):
            validate_resource_binding(binding, other_scope, resource_kind="builder_session")

    def test_resource_kind_confusion_is_rejected(self):
        binding = bind_resource(self.scope, resource_kind="memory", resource_id="memory-1")
        with self.assertRaises(PermissionError):
            validate_resource_binding(binding, self.scope, resource_kind="task")

    def test_tampering_is_rejected(self):
        binding = bind_resource(self.scope, resource_kind="task", resource_id="task-1")
        tampered = copy.deepcopy(binding)
        tampered["resource_id"] = "task-2"
        with self.assertRaises(ValueError):
            validate_resource_binding(tampered, self.scope, resource_kind="task")

    def test_binding_rejects_unknown_fields(self):
        binding = bind_resource(self.scope, resource_kind="file", resource_id="file-1")
        binding["extra"] = "ignored-by-old-code"
        with self.assertRaises(ValueError):
            validate_resource_binding(binding, self.scope, resource_kind="file")


if __name__ == "__main__":
    unittest.main()
