from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_SOURCE_KINDS = {"official", "primary", "news", "academic", "community", "repository", "documentation", "other"}
ALLOWED_STANCES = {"supports", "contradicts", "context"}
MAX_URL = 2048
MAX_EVIDENCE_PER_CLAIM = 32
MAX_AGE_SECONDS = 366 * 24 * 60 * 60


def _text_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def _scope_digest(chat_id: str, project_id: str, repo_scope: str) -> str:
    for value, label in ((chat_id, "chat_id"), (project_id, "project_id")):
        _text_id(value, label)
    if not isinstance(repo_scope, str) or not repo_scope or len(repo_scope) > 4096 or "\x00" in repo_scope:
        raise ValueError("invalid repo_scope")
    payload = json.dumps(
        {"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError(f"invalid {label}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {label}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _canonical_url(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_URL:
        raise ValueError("invalid source_url")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("source_url must be HTTP(S)")
    if parts.username is not None or parts.password is not None:
        raise ValueError("source_url credentials are forbidden")
    if parts.port is not None and not (1 <= parts.port <= 65535):
        raise ValueError("invalid source_url port")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("invalid source_url control character")
    # Fragments are client-side navigation and are not part of fetched source identity.
    netloc = parts.hostname.lower()
    if parts.port is not None:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))


def issue_evidence(
    *,
    evidence_id: str,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    claim_digest: str,
    source_url: str,
    source_kind: str,
    stance: str,
    content_digest: str,
    retrieved_at: str,
    observed_at: str,
) -> dict:
    evidence_id = _text_id(evidence_id, "evidence_id")
    claim_digest = _digest(claim_digest, "claim_digest")
    content_digest = _digest(content_digest, "content_digest")
    if source_kind not in ALLOWED_SOURCE_KINDS:
        raise ValueError("invalid source_kind")
    if stance not in ALLOWED_STANCES:
        raise ValueError("invalid stance")
    retrieved = _timestamp(retrieved_at, "retrieved_at")
    observed = _timestamp(observed_at, "observed_at")
    if retrieved > observed:
        raise ValueError("retrieved_at cannot be in the future")
    age = (observed - retrieved).total_seconds()
    if age > MAX_AGE_SECONDS:
        raise ValueError("research evidence is too old for canonical evidence state")

    return {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "scope_digest": _scope_digest(chat_id, project_id, repo_scope),
        "claim_digest": claim_digest,
        "source_url": _canonical_url(source_url),
        "source_kind": source_kind,
        "stance": stance,
        "content_digest": content_digest,
        "retrieved_at": retrieved.isoformat().replace("+00:00", "Z"),
    }


def validate_evidence(record: dict) -> dict:
    if not isinstance(record, dict):
        raise ValueError("evidence must be an object")
    required = {
        "schema_version", "evidence_id", "scope_digest", "claim_digest", "source_url",
        "source_kind", "stance", "content_digest", "retrieved_at",
    }
    if set(record) != required or record.get("schema_version") != 1:
        raise ValueError("invalid evidence schema")
    _text_id(record["evidence_id"], "evidence_id")
    _digest(record["scope_digest"], "scope_digest")
    _digest(record["claim_digest"], "claim_digest")
    _digest(record["content_digest"], "content_digest")
    if record["source_kind"] not in ALLOWED_SOURCE_KINDS or record["stance"] not in ALLOWED_STANCES:
        raise ValueError("invalid evidence classification")
    if _canonical_url(record["source_url"]) != record["source_url"]:
        raise ValueError("source_url is not canonical")
    _timestamp(record["retrieved_at"], "retrieved_at")
    return dict(record)


def assert_evidence_access(record: dict, *, chat_id: str, project_id: str, repo_scope: str) -> None:
    validated = validate_evidence(record)
    expected = _scope_digest(chat_id, project_id, repo_scope)
    if validated["scope_digest"] != expected:
        raise ValueError("research evidence scope mismatch")


def bind_claim_evidence(*, claim_digest: str, records: list[dict], chat_id: str, project_id: str, repo_scope: str) -> dict:
    claim_digest = _digest(claim_digest, "claim_digest")
    if not isinstance(records, list) or not records or len(records) > MAX_EVIDENCE_PER_CLAIM:
        raise ValueError("invalid evidence set size")
    seen_ids: set[str] = set()
    seen_source_versions: set[tuple[str, str]] = set()
    normalized = []
    for record in records:
        validated = validate_evidence(record)
        assert_evidence_access(validated, chat_id=chat_id, project_id=project_id, repo_scope=repo_scope)
        if validated["claim_digest"] != claim_digest:
            raise ValueError("evidence belongs to another claim")
        if validated["evidence_id"] in seen_ids:
            raise ValueError("duplicate evidence_id")
        source_version = (validated["source_url"], validated["content_digest"])
        if source_version in seen_source_versions:
            raise ValueError("duplicate source version")
        seen_ids.add(validated["evidence_id"])
        seen_source_versions.add(source_version)
        normalized.append(validated)
    normalized.sort(key=lambda row: row["evidence_id"])
    digest_payload = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": 1,
        "claim_digest": claim_digest,
        "scope_digest": _scope_digest(chat_id, project_id, repo_scope),
        "evidence_count": len(normalized),
        "has_support": any(row["stance"] == "supports" for row in normalized),
        "has_contradiction": any(row["stance"] == "contradicts" for row in normalized),
        "evidence_set_digest": hashlib.sha256(digest_payload).hexdigest(),
    }
