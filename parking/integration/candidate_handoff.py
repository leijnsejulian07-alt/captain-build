from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
MAX_ARTIFACTS = 256
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
SCHEMA_VERSION = 1
SOURCE_KIND = "github_parking"

_HANDOFF_FIELDS = {
    "schema_version", "source_kind", "repository", "source_ref",
    "head_sha", "head_tree_sha", "base_sha", "manifest_digest",
    "repo_scope_hash", "artifacts", "handoff_digest",
}
_ARTIFACT_FIELDS = {"path", "sha256", "size"}


def _sha1(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA1_RE.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def _repo(value: Any) -> str:
    if not isinstance(value, str) or not REPO_RE.fullmatch(value) or ".." in value:
        raise ValueError("invalid repository")
    return value


def _ref(value: Any) -> str:
    if not isinstance(value, str) or not REF_RE.fullmatch(value):
        raise ValueError("invalid source ref")
    if value.startswith("/") or value.endswith("/") or "//" in value or ".." in value:
        raise ValueError("unsafe source ref")
    return value


def _artifact_path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 300:
        raise ValueError("invalid artifact path")
    if "\\" in value or value.startswith("/") or value.endswith("/"):
        raise ValueError("unsafe artifact path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("unsafe artifact path")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("unsafe artifact path")
    return value


def repo_scope_hash(repo_scope: str) -> str:
    if not isinstance(repo_scope, str) or not repo_scope or len(repo_scope) > 4096:
        raise ValueError("invalid repo scope")
    return hashlib.sha256(repo_scope.encode("utf-8")).hexdigest()


def _normalize_artifacts(value: Any) -> list[dict]:
    if not isinstance(value, list) or len(value) > MAX_ARTIFACTS:
        raise ValueError("invalid artifacts")
    normalized: list[dict] = []
    seen: set[str] = set()
    for row in value:
        if not isinstance(row, dict) or set(row) != _ARTIFACT_FIELDS:
            raise ValueError("invalid artifact record")
        path = _artifact_path(row["path"])
        if path in seen:
            raise ValueError("duplicate artifact path")
        seen.add(path)
        size = row["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > MAX_ARTIFACT_BYTES:
            raise ValueError("invalid artifact size")
        normalized.append({
            "path": path,
            "sha256": _sha256(row["sha256"], "artifact digest"),
            "size": size,
        })
    return sorted(normalized, key=lambda row: row["path"])


def _payload(
    *,
    repository: str,
    source_ref: str,
    head_sha: str,
    head_tree_sha: str,
    base_sha: str,
    manifest_digest: str,
    repo_scope_hash_value: str,
    artifacts: list[dict],
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_kind": SOURCE_KIND,
        "repository": _repo(repository),
        "source_ref": _ref(source_ref),
        "head_sha": _sha1(head_sha, "head sha"),
        "head_tree_sha": _sha1(head_tree_sha, "head tree sha"),
        "base_sha": _sha1(base_sha, "base sha"),
        "manifest_digest": _sha256(manifest_digest, "manifest digest"),
        "repo_scope_hash": _sha256(repo_scope_hash_value, "repo scope hash"),
        "artifacts": _normalize_artifacts(artifacts),
    }


def _digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_handoff(
    *,
    repository: str,
    source_ref: str,
    head_sha: str,
    head_tree_sha: str,
    base_sha: str,
    manifest_digest: str,
    repo_scope: str,
    artifacts: list[dict],
) -> dict:
    payload = _payload(
        repository=repository,
        source_ref=source_ref,
        head_sha=head_sha,
        head_tree_sha=head_tree_sha,
        base_sha=base_sha,
        manifest_digest=manifest_digest,
        repo_scope_hash_value=repo_scope_hash(repo_scope),
        artifacts=artifacts,
    )
    return {**payload, "handoff_digest": _digest(payload)}


def verify_handoff(
    handoff: dict,
    *,
    expected_repository: str,
    expected_source_ref: str,
    expected_head_sha: str,
    expected_head_tree_sha: str,
    expected_base_sha: str,
    expected_manifest_digest: str,
    repo_scope: str,
) -> dict:
    if not isinstance(handoff, dict) or set(handoff) != _HANDOFF_FIELDS:
        raise ValueError("invalid handoff schema")
    if handoff.get("schema_version") != SCHEMA_VERSION or handoff.get("source_kind") != SOURCE_KIND:
        raise ValueError("unsupported handoff")
    payload = _payload(
        repository=handoff["repository"],
        source_ref=handoff["source_ref"],
        head_sha=handoff["head_sha"],
        head_tree_sha=handoff["head_tree_sha"],
        base_sha=handoff["base_sha"],
        manifest_digest=handoff["manifest_digest"],
        repo_scope_hash_value=handoff["repo_scope_hash"],
        artifacts=handoff["artifacts"],
    )
    supplied_digest = _sha256(handoff["handoff_digest"], "handoff digest")
    if _digest(payload) != supplied_digest:
        raise ValueError("handoff content was modified")

    expected = {
        "repository": _repo(expected_repository),
        "source_ref": _ref(expected_source_ref),
        "head_sha": _sha1(expected_head_sha, "expected head sha"),
        "head_tree_sha": _sha1(expected_head_tree_sha, "expected tree sha"),
        "base_sha": _sha1(expected_base_sha, "expected base sha"),
        "manifest_digest": _sha256(expected_manifest_digest, "expected manifest digest"),
        "repo_scope_hash": repo_scope_hash(repo_scope),
    }
    for key, value in expected.items():
        if payload[key] != value:
            raise ValueError(f"handoff {key} mismatch")

    return {
        "schema_version": SCHEMA_VERSION,
        "source_kind": SOURCE_KIND,
        "handoff_digest": supplied_digest,
        "artifact_count": len(payload["artifacts"]),
    }
