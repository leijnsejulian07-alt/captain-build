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
        self.principal = "captain"
        self.epoch = 7
        self.generation = 3

    def _bind(self, kind, resource_id, operations=("read",), principal=None):
        return bind_resource(
            self.scope,
            principal_id=self.principal if principal is None else principal,
            state_epoch=self.epoch,
            resource_generation=self.generation,
            resource_kind=kind,
            resource_id=resource_id,
            allowed_operations=operations,
        )

    def _validate(self, binding, kind, operation="read", principal=None):
        return validate_resource_binding(
            binding,
            self.scope,
            expected_principal_id=self.principal if principal is None else principal,
            expected_state_epoch=self.epoch,
            expected_resource_generation=self.generation,
            resource_kind=kind,
            requested_operation=operation,
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
        with self.assertRaises(ValueError):
            parse_scope(dict(self.scope, token="secret"))
        with self.assertRaises(ValueError):
            parse_scope(dict(self.scope, repo_scope="owner/repo#../../outside"))

    def test_resource_binding_round_trip(self):
        binding = self._bind("preview_session", "preview-1", ("read", "stop"))
        self.assertEqual(self._validate(binding, "preview_session", "stop"), binding)

    def test_cross_project_resource_reuse_is_rejected(self):
        binding = self._bind("builder_session", "builder-1")
        with self.assertRaises(PermissionError):
            validate_resource_binding(
                binding,
                dict(self.scope, project_id="project-beta"),
                expected_principal_id=self.principal,
                expected_state_epoch=self.epoch,
                expected_resource_generation=self.generation,
                resource_kind="builder_session",
                requested_operation="read",
            )

    def test_cross_principal_resource_reuse_is_rejected(self):
        binding = self._bind("file", "file-1", ("read",), principal="plugin-alpha")
        with self.assertRaises(PermissionError):
            self._validate(binding, "file", principal="plugin-beta")

    def test_principal_tampering_is_rejected_by_digest(self):
        binding = self._bind("memory", "memory-1", principal="plugin-alpha")
        tampered = copy.deepcopy(binding)
        tampered["principal_id"] = "plugin-beta"
        with self.assertRaises(ValueError):
            self._validate(tampered, "memory", principal="plugin-beta")

    def test_principal_is_required_and_strictly_validated(self):
        for principal in ("", "../plugin", "plugin/other", True):
            with self.subTest(principal=principal):
                with self.assertRaises(ValueError):
                    self._bind("file", "file-1", principal=principal)

    def test_stale_resource_after_project_state_reset_is_rejected(self):
        binding = self._bind("builder_session", "builder-1")
        with self.assertRaises(PermissionError):
            validate_resource_binding(
                binding,
                self.scope,
                expected_principal_id=self.principal,
                expected_state_epoch=self.epoch + 1,
                expected_resource_generation=self.generation,
                resource_kind="builder_session",
                requested_operation="read",
            )

    def test_same_epoch_reissued_resource_rejects_old_generation(self):
        binding = self._bind("preview_session", "preview-1")
        with self.assertRaises(PermissionError):
            validate_resource_binding(
                binding,
                self.scope,
                expected_principal_id=self.principal,
                expected_state_epoch=self.epoch,
                expected_resource_generation=self.generation + 1,
                resource_kind="preview_session",
                requested_operation="read",
            )

    def test_generation_tampering_is_rejected_by_digest(self):
        binding = self._bind("task", "task-1")
        tampered = copy.deepcopy(binding)
        tampered["resource_generation"] = self.generation + 1
        with self.assertRaises(ValueError):
            validate_resource_binding(
                tampered,
                self.scope,
                expected_principal_id=self.principal,
                expected_state_epoch=self.epoch,
                expected_resource_generation=self.generation + 1,
                resource_kind="task",
                requested_operation="read",
            )

    def test_epoch_tampering_is_rejected_by_digest(self):
        binding = self._bind("task", "task-1")
        tampered = copy.deepcopy(binding)
        tampered["state_epoch"] = self.epoch + 1
        with self.assertRaises(ValueError):
            validate_resource_binding(
                tampered,
                self.scope,
                expected_principal_id=self.principal,
                expected_state_epoch=self.epoch + 1,
                expected_resource_generation=self.generation,
                resource_kind="task",
                requested_operation="read",
            )

    def test_invalid_epochs_and_generations_fail_closed(self):
        for value in (0, -1, True, 2**63):
            with self.subTest(epoch=value):
                with self.assertRaises(ValueError):
                    bind_resource(self.scope, principal_id=self.principal, state_epoch=value, resource_generation=self.generation, resource_kind="file", resource_id="file-1", allowed_operations=("read",))
            with self.subTest(generation=value):
                with self.assertRaises(ValueError):
                    bind_resource(self.scope, principal_id=self.principal, state_epoch=self.epoch, resource_generation=value, resource_kind="file", resource_id="file-1", allowed_operations=("read",))

    def test_read_only_binding_denies_write(self):
        binding = self._bind("file", "file-1", ("read",))
        with self.assertRaises(PermissionError):
            self._validate(binding, "file", "write")

    def test_operation_tampering_is_rejected_by_digest(self):
        binding = self._bind("file", "file-1", ("read",))
        tampered = copy.deepcopy(binding)
        tampered["allowed_operations"] = ["read", "write"]
        with self.assertRaises(ValueError):
            self._validate(tampered, "file", "write")

    def test_operations_must_be_canonical_unique_and_bounded(self):
        for operations in ((), ("write", "read"), ("read", "read"), tuple(f"op{i}" for i in range(17)), ("../write",)):
            with self.subTest(operations=operations):
                with self.assertRaises(ValueError):
                    self._bind("file", "file-1", operations)

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
