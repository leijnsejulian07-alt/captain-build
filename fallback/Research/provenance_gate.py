"""Fail-closed research provenance gate for Captain fallback work.

The gate binds evidence to the same authority tuple used by Project State and
refuses reuse across chat/project/repository/epoch boundaries. Public receipts
store only minimized source metadata and hashes; raw page text, credentials,
query strings, fragments and secret-like values are not persisted here.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit


class ProvenanceError(ValueError):
    """Raised when evidence cannot be safely accepted or reused."""


@dataclass(frozen=True)
class Authority:
    chat_id: str
    project_id: str
    repo_scope: str
    state_epoch: str

    def validate(self) -> None:
        for name, value in (
            ("chat_id", self.chat_id),
            ("project_id", self.project_id),
            ("repo_scope", self.repo_scope),
            ("state_epoch", self.state_epoch),
        ):
            if not value or not value.strip():
                raise ProvenanceError(f"missing authority field: {name}")

    @property
    def digest(self) -> str:
        self.validate()
        payload = "\x1f".join(
            (self.chat_id, self.project_id, self.repo_scope, self.state_epoch)
        )
        return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceReceipt:
    evidence_id: str
    authority_digest: str
    source_url: str
    source_hash: str
    claim_hash: str
    retrieved_at: str
    source_kind: str = "web"


_ALLOWED_SOURCE_KINDS = {"web", "official_docs", "github", "file", "connector"}
_SECRET_MARKERS = (
    "authorization:",
    "bearer ",
    "api_key=",
    "apikey=",
    "access_token=",
    "token=",
    "password=",
    "secret=",
    "sk-",
)


def _reject_secret_like(value: str, field: str) -> None:
    lowered = value.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        raise ProvenanceError(f"secret-like material rejected in {field}")
    if "\n" in value or "\r" in value:
        raise ProvenanceError(f"multiline material rejected in {field}")


def minimize_url(url: str) -> str:
    """Return origin+path only, dropping userinfo, query and fragment."""
    _reject_secret_like(url, "source_url")
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise ProvenanceError("source_url must be absolute http(s)")
    host = parts.hostname.lower()
    if parts.port:
        host = f"{host}:{parts.port}"
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), host, path, "", ""))


def _content_hash(value: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProvenanceError(f"{field} must be non-empty text")
    return sha256(value.encode("utf-8")).hexdigest()


def create_receipt(
    *,
    authority: Authority,
    evidence_id: str,
    source_url: str,
    source_text: str,
    claim_text: str,
    retrieved_at: str,
    source_kind: str = "web",
) -> EvidenceReceipt:
    authority.validate()
    if not evidence_id or len(evidence_id) > 160:
        raise ProvenanceError("invalid evidence_id")
    _reject_secret_like(evidence_id, "evidence_id")
    if source_kind not in _ALLOWED_SOURCE_KINDS:
        raise ProvenanceError("unsupported source_kind")
    if not retrieved_at or len(retrieved_at) > 80:
        raise ProvenanceError("invalid retrieved_at")
    _reject_secret_like(retrieved_at, "retrieved_at")

    return EvidenceReceipt(
        evidence_id=evidence_id,
        authority_digest=authority.digest,
        source_url=minimize_url(source_url),
        source_hash=_content_hash(source_text, "source_text"),
        claim_hash=_content_hash(claim_text, "claim_text"),
        retrieved_at=retrieved_at,
        source_kind=source_kind,
    )


def authorize_reuse(receipt: EvidenceReceipt, current: Authority) -> EvidenceReceipt:
    """Fail closed unless evidence belongs to the exact current authority."""
    current.validate()
    if receipt.authority_digest != current.digest:
        raise ProvenanceError("evidence authority mismatch or stale epoch")
    if receipt.source_kind not in _ALLOWED_SOURCE_KINDS:
        raise ProvenanceError("unsupported source_kind")
    if len(receipt.source_hash) != 64 or len(receipt.claim_hash) != 64:
        raise ProvenanceError("invalid evidence hashes")
    return receipt


def public_receipt(receipt: EvidenceReceipt, current: Authority) -> dict[str, str]:
    """Safe UI/log projection: no raw source/claim text or auth material."""
    authorize_reuse(receipt, current)
    return {
        "evidence_id": receipt.evidence_id,
        "source_url": receipt.source_url,
        "source_hash": receipt.source_hash,
        "claim_hash": receipt.claim_hash,
        "retrieved_at": receipt.retrieved_at,
        "source_kind": receipt.source_kind,
    }
