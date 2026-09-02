from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_VERSION = 2
MAX_EVIDENCE_AGE = timedelta(minutes=15)
MAX_FUTURE_SKEW = timedelta(minutes=1)


def _parse_time(value: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid prerequisite evidence timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid prerequisite evidence timestamp") from exc
    if dt.tzinfo is None:
        raise ValueError("prerequisite evidence timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(prerequisite_id: str, local_base_sha: str, verifier: str, verified_at: str) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "prerequisite_id": prerequisite_id,
        "local_base_sha": local_base_sha,
        "verifier": verifier,
        "verified_at": verified_at,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_verified_prerequisite(
    prerequisite_id: str,
    local_base_sha: str,
    verifier: str,
    *,
    verified_at: str | None = None,
) -> dict:
    if not isinstance(prerequisite_id, str) or not ID_RE.fullmatch(prerequisite_id):
        raise ValueError("invalid prerequisite id")
    if not isinstance(local_base_sha, str) or not SHA_RE.fullmatch(local_base_sha):
        raise ValueError("invalid local base sha")
    if not isinstance(verifier, str) or not ID_RE.fullmatch(verifier):
        raise ValueError("invalid verifier id")
    verified_dt = datetime.now(timezone.utc) if verified_at is None else _parse_time(verified_at)
    verified_at = _iso(verified_dt)
    return {
        "schema_version": SCHEMA_VERSION,
        "prerequisite_id": prerequisite_id,
        "local_base_sha": local_base_sha,
        "verifier": verifier,
        "verified_at": verified_at,
        "evidence_digest": _digest(prerequisite_id, local_base_sha, verifier, verified_at),
    }


def validate_external_prerequisites(
    manifest: dict,
    evidence: dict,
    local_base_sha: str,
    *,
    now: str | None = None,
) -> set[str]:
    if not isinstance(manifest, dict) or not isinstance(evidence, dict):
        raise ValueError("invalid external prerequisite inputs")
    if not isinstance(local_base_sha, str) or not SHA_RE.fullmatch(local_base_sha):
        raise ValueError("invalid local base sha")
    now_dt = datetime.now(timezone.utc) if now is None else _parse_time(now)
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
            "schema_version", "prerequisite_id", "local_base_sha", "verifier", "verified_at", "evidence_digest"
        }:
            raise ValueError("malformed external prerequisite evidence")
        if row.get("schema_version") != SCHEMA_VERSION or row.get("prerequisite_id") != prerequisite_id:
            raise ValueError("external prerequisite identity mismatch")
        if row.get("local_base_sha") != local_base_sha:
            raise ValueError("external prerequisite evidence is stale")
        verifier = row.get("verifier")
        if not isinstance(verifier, str) or not ID_RE.fullmatch(verifier):
            raise ValueError("invalid verifier id")
        verified_at = row.get("verified_at")
        verified_dt = _parse_time(verified_at)
        if verified_dt > now_dt + MAX_FUTURE_SKEW:
            raise ValueError("external prerequisite evidence timestamp is in the future")
        if now_dt - verified_dt > MAX_EVIDENCE_AGE:
            raise ValueError("external prerequisite evidence is expired")
        digest = row.get("evidence_digest")
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            raise ValueError("invalid external prerequisite evidence digest")
        if digest != _digest(prerequisite_id, local_base_sha, verifier, verified_at):
            raise ValueError("external prerequisite evidence was modified")
        ready.add(prerequisite_id)
    return ready
