from __future__ import annotations

import hashlib
import json
import re

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_VERSION = 1


def _digest(prerequisite_id: str, local_base_sha: str, verifier: str) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "prerequisite_id": prerequisite_id,
        "local_base_sha": local_base_sha,
        "verifier": verifier,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_verified_prerequisite(prerequisite_id: str, local_base_sha: str, verifier: str) -> dict:
    if not isinstance(prerequisite_id, str) or not ID_RE.fullmatch(prerequisite_id):
        raise ValueError("invalid prerequisite id")
    if not isinstance(local_base_sha, str) or not SHA_RE.fullmatch(local_base_sha):
        raise ValueError("invalid local base sha")
    if not isinstance(verifier, str) or not ID_RE.fullmatch(verifier):
        raise ValueError("invalid verifier id")
    return {
        "schema_version": SCHEMA_VERSION,
        "prerequisite_id": prerequisite_id,
        "local_base_sha": local_base_sha,
        "verifier": verifier,
        "evidence_digest": _digest(prerequisite_id, local_base_sha, verifier),
    }


def validate_external_prerequisites(manifest: dict, evidence: dict, local_base_sha: str) -> set[str]:
    if not isinstance(manifest, dict) or not isinstance(evidence, dict):
        raise ValueError("invalid external prerequisite inputs")
    if not isinstance(local_base_sha, str) or not SHA_RE.fullmatch(local_base_sha):
        raise ValueError("invalid local base sha")
    declared = manifest.get("external_prerequisites")
    if not isinstance(declared, list) or any(not isinstance(x, str) or not ID_RE.fullmatch(x) for x in declared):
        raise ValueError("invalid manifest external prerequisites")
    if len(declared) != len(set(declared)):
        raise ValueError("duplicate external prerequisite")
    if set(evidence) - set(declared):
        raise ValueError("unknown external prerequisite evidence")

    ready: set[str] = set()
    for prerequisite_id, row in evidence.items():
        if not isinstance(row, dict) or set(row) != {
            "schema_version", "prerequisite_id", "local_base_sha", "verifier", "evidence_digest"
        }:
            raise ValueError("malformed external prerequisite evidence")
        if row.get("schema_version") != SCHEMA_VERSION or row.get("prerequisite_id") != prerequisite_id:
            raise ValueError("external prerequisite identity mismatch")
        if row.get("local_base_sha") != local_base_sha:
            raise ValueError("external prerequisite evidence is stale")
        verifier = row.get("verifier")
        if not isinstance(verifier, str) or not ID_RE.fullmatch(verifier):
            raise ValueError("invalid verifier id")
        digest = row.get("evidence_digest")
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            raise ValueError("invalid external prerequisite evidence digest")
        if digest != _digest(prerequisite_id, local_base_sha, verifier):
            raise ValueError("external prerequisite evidence was modified")
        ready.add(prerequisite_id)
    return ready
