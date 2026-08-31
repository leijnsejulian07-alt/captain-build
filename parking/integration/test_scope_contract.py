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
        self.epoch = 7

    def _bind(self, kind, resource_id):
        return bind_resource(self.scope, state_epoch=self.epoch, resource_kind=kind, resource_id=resource_id)

    def _validate(self, binding, kind):
        return validate_resource_binding(
            binding,
            self.scope,
            expected_state_epoch=self.epoch,
            resource_kind=kind,
        )

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
        binding = self._bind("preview_session", "preview-1")
        self.assertEqual(self._validate(binding, "preview_session"), binding)

    def test_cross_project_resource_reuse_is_rejected(self):
        binding = self._bind("builder_session", "builder-1")
        other_scope = dict(self.scope, project_id="project-beta")
        with self.assertRaises(PermissionError):
            validate_resource_binding(
                binding,
                other_scope,
                expected_state_epoch=self.epoch,
                resource_kind="builder_session",
            )

    def test_stale_resource_after_project_state_reset_is_rejected(self):
        binding = self._bind("builder_session", "builder-1")
        with self.assertRaises(PermissionError):
            validate_resource_binding(
                binding,
                self.scope,
                expected_state_epoch=self.epoch + 1,
                resource_kind="builder_session",
            )

    def test_epoch_tampering_is_rejected_by_digest(self):
        binding = self._bind("task", "task-1")
        tampered = copy.deepcopy(binding)
        tampered["state_epoch"] = self.epoch + 1
        with self.assertRaises(ValueError):
            validate_resource_binding(
                tampered,
                self.scope,
                expected_state_epoch=self.epoch + 1,
                resource_kind="task",
            )

    def test_invalid_epochs_fail_closed(self):
        for value in (0, -1, True, 2**63):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    bind_resource(self.scope, state_epoch=value, resource_kind="file", resource_id="file-1")

    def test_resource_kind_confusion_is_rejected(self):
        binding = self._bind("memory", "memory-1")
        with self.assertRaises(PermissionError):
            self._validate(binding, "task")

    def test_tampering_is_rejected(self):
        binding = self._bind("task", "task-1")
        tampered = copy.deepcopy(binding)
        tampered["resource_id"] = "task-2"
        with self.assertRaises(ValueError):
            self._validate(tampered, "task")

    def test_binding_rejects_unknown_fields(self):
        binding = self._bind("file", "file-1")
        binding["extra"] = "ignored-by-old-code"
        with self.assertRaises(ValueError):
            self._validate(binding, "file")


if __name__ == "__main__":
    unittest.main()
