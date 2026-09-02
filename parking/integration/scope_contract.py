from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

_SCOPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REPO_SCOPE_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(?:#[A-Za-z0-9._/@:-]{1,160})?$")
_RESOURCE_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_VERSION = 5
MAX_STATE_EPOCH = 2**63 - 1
MAX_RESOURCE_GENERATION = 2**63 - 1
MAX_ALLOWED_OPERATIONS = 16


@dataclass(frozen=True)
class ScopeKey:
    chat_id: str
    project_id: str
    repo_scope: str

    def as_dict(self) -> dict[str, str]:
        return {
            "chat_id": self.chat_id,
            "project_id": self.project_id,
            "repo_scope": self.repo_scope,
        }


def _validate_scope_id(name: str, value: object) -> str:
    if not isinstance(value, str) or not _SCOPE_ID_RE.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _validate_repo_scope(value: object) -> str:
    if not isinstance(value, str) or len(value) > 256 or not _REPO_SCOPE_RE.fullmatch(value):
        raise ValueError("invalid repo_scope")
    if ".." in value or value.startswith("/") or chr(92) in value:
        raise ValueError("unsafe repo_scope")
    return value


def _validate_state_epoch(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > MAX_STATE_EPOCH:
        raise ValueError("invalid state_epoch")
    return value


def _validate_resource_generation(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > MAX_RESOURCE_GENERATION:
        raise ValueError("invalid resource_generation")
    return value


def _validate_principal_id(value: object) -> str:
    return _validate_scope_id("principal_id", value)


def _validate_operation(value: object) -> str:
    if not isinstance(value, str) or not _OPERATION_RE.fullmatch(value):
        raise ValueError("invalid resource operation")
    return value


def _validate_allowed_operations(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("allowed_operations must be a sequence")
    if not value or len(value) > MAX_ALLOWED_OPERATIONS:
        raise ValueError("invalid allowed_operations count")
    operations = tuple(_validate_operation(item) for item in value)
    if len(set(operations)) != len(operations):
        raise ValueError("duplicate allowed operation")
    if tuple(sorted(operations)) != operations:
        raise ValueError("allowed_operations must be canonical")
    return operations


def parse_scope(value: Mapping[str, object] | ScopeKey) -> ScopeKey:
    if isinstance(value, ScopeKey):
        scope = value
    elif isinstance(value, Mapping) and set(value) == {"chat_id", "project_id", "repo_scope"}:
        scope = ScopeKey(
            chat_id=_validate_scope_id("chat_id", value.get("chat_id")),
            project_id=_validate_scope_id("project_id", value.get("project_id")),
            repo_scope=_validate_repo_scope(value.get("repo_scope")),
        )
    else:
        raise ValueError("scope must contain exactly chat_id, project_id and repo_scope")

    _validate_scope_id("chat_id", scope.chat_id)
    _validate_scope_id("project_id", scope.project_id)
    _validate_repo_scope(scope.repo_scope)
    return scope


def assert_same_scope(expected: Mapping[str, object] | ScopeKey, actual: Mapping[str, object] | ScopeKey) -> ScopeKey:
    expected_scope = parse_scope(expected)
    actual_scope = parse_scope(actual)
    if expected_scope != actual_scope:
        raise PermissionError("scope mismatch")
    return actual_scope


def _binding_digest(
    scope: ScopeKey,
    principal_id: str,
    resource_kind: str,
    resource_id: str,
    state_epoch: int,
    resource_generation: int,
    allowed_operations: tuple[str, ...],
) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "scope": scope.as_dict(),
        "principal_id": principal_id,
        "state_epoch": state_epoch,
        "resource_generation": resource_generation,
        "resource_kind": resource_kind,
        "resource_id": resource_id,
        "allowed_operations": list(allowed_operations),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bind_resource(
    scope: Mapping[str, object] | ScopeKey,
    *,
    principal_id: str,
    state_epoch: int,
    resource_generation: int,
    resource_kind: str,
    resource_id: str,
    allowed_operations: Sequence[str],
) -> dict[str, object]:
    parsed = parse_scope(scope)
    principal = _validate_principal_id(principal_id)
    epoch = _validate_state_epoch(state_epoch)
    generation = _validate_resource_generation(resource_generation)
    operations = _validate_allowed_operations(allowed_operations)
    if not isinstance(resource_kind, str) or not _RESOURCE_KIND_RE.fullmatch(resource_kind):
        raise ValueError("invalid resource_kind")
    if not isinstance(resource_id, str) or not _RESOURCE_ID_RE.fullmatch(resource_id):
        raise ValueError("invalid resource_id")
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": parsed.as_dict(),
        "principal_id": principal,
        "state_epoch": epoch,
        "resource_generation": generation,
        "resource_kind": resource_kind,
        "resource_id": resource_id,
        "allowed_operations": list(operations),
        "binding_digest": _binding_digest(parsed, principal, resource_kind, resource_id, epoch, generation, operations),
    }


def validate_resource_binding(
    binding: Mapping[str, object],
    expected_scope: Mapping[str, object] | ScopeKey,
    *,
    expected_principal_id: str,
    expected_state_epoch: int,
    expected_resource_generation: int,
    requested_operation: str,
    resource_kind: str | None = None,
) -> dict[str, object]:
    required = {
        "schema_version",
        "scope",
        "principal_id",
        "state_epoch",
        "resource_generation",
        "resource_kind",
        "resource_id",
        "allowed_operations",
        "binding_digest",
    }
    if not isinstance(binding, Mapping) or set(binding) != required or binding.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid resource scope binding")

    actual_scope = assert_same_scope(expected_scope, binding.get("scope"))
    expected_principal = _validate_principal_id(expected_principal_id)
    actual_principal = _validate_principal_id(binding.get("principal_id"))
    if actual_principal != expected_principal:
        raise PermissionError("resource principal mismatch")
    expected_epoch = _validate_state_epoch(expected_state_epoch)
    actual_epoch = _validate_state_epoch(binding.get("state_epoch"))
    if actual_epoch != expected_epoch:
        raise PermissionError("resource state epoch mismatch")
    expected_generation = _validate_resource_generation(expected_resource_generation)
    actual_generation = _validate_resource_generation(binding.get("resource_generation"))
    if actual_generation != expected_generation:
        raise PermissionError("resource generation mismatch")

    kind = binding.get("resource_kind")
    resource_id = binding.get("resource_id")
    operations = _validate_allowed_operations(binding.get("allowed_operations"))
    operation = _validate_operation(requested_operation)
    digest = binding.get("binding_digest")
    if not isinstance(kind, str) or not _RESOURCE_KIND_RE.fullmatch(kind):
        raise ValueError("invalid resource_kind")
    if resource_kind is not None and kind != resource_kind:
        raise PermissionError("resource kind mismatch")
    if not isinstance(resource_id, str) or not _RESOURCE_ID_RE.fullmatch(resource_id):
        raise ValueError("invalid resource_id")
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise ValueError("invalid binding digest")
    if digest != _binding_digest(
        actual_scope,
        actual_principal,
        kind,
        resource_id,
        actual_epoch,
        actual_generation,
        operations,
    ):
        raise ValueError("resource scope binding was modified")
    if operation not in operations:
        raise PermissionError("resource operation is not allowed")
    return dict(binding)
