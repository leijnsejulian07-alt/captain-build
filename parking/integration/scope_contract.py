from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

_SCOPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REPO_SCOPE_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(?:#[A-Za-z0-9._/@:-]{1,160})?$")
_RESOURCE_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_VERSION = 1


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
    if ".." in value or value.startswith(("/", "\\")) or "\\" in value:
        raise ValueError("unsafe repo_scope")
    return value


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


def _binding_digest(scope: ScopeKey, resource_kind: str, resource_id: str) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "scope": scope.as_dict(),
        "resource_kind": resource_kind,
        "resource_id": resource_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bind_resource(
    scope: Mapping[str, object] | ScopeKey,
    *,
    resource_kind: str,
    resource_id: str,
) -> dict[str, object]:
    parsed = parse_scope(scope)
    if not isinstance(resource_kind, str) or not _RESOURCE_KIND_RE.fullmatch(resource_kind):
        raise ValueError("invalid resource_kind")
    if not isinstance(resource_id, str) or not _RESOURCE_ID_RE.fullmatch(resource_id):
        raise ValueError("invalid resource_id")
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": parsed.as_dict(),
        "resource_kind": resource_kind,
        "resource_id": resource_id,
        "binding_digest": _binding_digest(parsed, resource_kind, resource_id),
    }


def validate_resource_binding(
    binding: Mapping[str, object],
    expected_scope: Mapping[str, object] | ScopeKey,
    *,
    resource_kind: str | None = None,
) -> dict[str, object]:
    required = {"schema_version", "scope", "resource_kind", "resource_id", "binding_digest"}
    if not isinstance(binding, Mapping) or set(binding) != required or binding.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid resource scope binding")

    actual_scope = assert_same_scope(expected_scope, binding.get("scope"))
    kind = binding.get("resource_kind")
    resource_id = binding.get("resource_id")
    digest = binding.get("binding_digest")
    if not isinstance(kind, str) or not _RESOURCE_KIND_RE.fullmatch(kind):
        raise ValueError("invalid resource_kind")
    if resource_kind is not None and kind != resource_kind:
        raise PermissionError("resource kind mismatch")
    if not isinstance(resource_id, str) or not _RESOURCE_ID_RE.fullmatch(resource_id):
        raise ValueError("invalid resource_id")
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise ValueError("invalid binding digest")
    if digest != _binding_digest(actual_scope, kind, resource_id):
        raise ValueError("resource scope binding was modified")
    return dict(binding)
