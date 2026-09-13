from __future__ import annotations

import hashlib
import json
import re
from typing import Mapping

from parking.integration.builder_output_scope import authorize_builder_output

SCHEMA_VERSION = 1
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*['\"]?([^\s'\";,]{8,})"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def redact_diff(diff_text: str) -> tuple[str, int]:
    """Return a reviewable diff with likely credentials removed.

    This is intentionally conservative. A positive secret finding blocks apply; callers
    must remediate the candidate change instead of overriding the scan.
    """
    if not isinstance(diff_text, str):
        raise ValueError("diff_text must be text")
    if len(diff_text.encode("utf-8")) > 2_000_000:
        raise ValueError("diff too large for inline review gate")

    redacted = diff_text
    findings = 0
    for pattern in _SECRET_PATTERNS:
        redacted, count = pattern.subn("[REDACTED_SECRET]", redacted)
        findings += count
    return redacted, findings


def issue_review_receipt(
    *,
    diff_output: Mapping[str, object],
    session: Mapping[str, object],
    diff_text: str,
) -> dict[str, object]:
    """Issue metadata for a reviewed builder diff without persisting the diff body."""
    if diff_output.get("kind") != "diff":
        raise ValueError("review gate requires a diff output")
    redacted, findings = redact_diff(diff_text)
    content_digest = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()
    if content_digest != diff_output.get("content_digest"):
        raise ValueError("diff body does not match output handle")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "session_binding_digest": session.get("binding_digest"),
        "output_binding_digest": diff_output.get("output_binding_digest"),
        "content_digest": content_digest,
        "redacted_digest": hashlib.sha256(redacted.encode("utf-8")).hexdigest(),
        "secret_findings": findings,
        "apply_blocked": findings > 0,
    }
    if not isinstance(payload["session_binding_digest"], str):
        raise ValueError("invalid builder session binding")
    if not isinstance(payload["output_binding_digest"], str):
        raise ValueError("invalid builder output binding")
    return {**payload, "review_binding_digest": _digest(payload)}


def authorize_apply(
    receipt: Mapping[str, object],
    *,
    diff_output: Mapping[str, object],
    session: Mapping[str, object],
    chat_id: str,
    project_id: str,
    repo_scope: str,
    session_id: str,
    repo_head: str,
    worktree_digest: str,
    state_epoch: int,
    now: str,
    explicit_approval: bool,
) -> dict[str, object]:
    """Authorize apply only for the exact current reviewed diff and active authority."""
    required = {
        "schema_version",
        "session_binding_digest",
        "output_binding_digest",
        "content_digest",
        "redacted_digest",
        "secret_findings",
        "apply_blocked",
        "review_binding_digest",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != required:
        raise ValueError("invalid review receipt schema")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported review receipt schema")
    if explicit_approval is not True:
        raise PermissionError("explicit review approval required")
    if receipt.get("apply_blocked") is not False or receipt.get("secret_findings") != 0:
        raise PermissionError("apply blocked by secret scan")

    authorized = authorize_builder_output(
        diff_output,
        session=session,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        session_id=session_id,
        repo_head=repo_head,
        worktree_digest=worktree_digest,
        state_epoch=state_epoch,
        now=now,
    )
    if authorized.get("kind") != "diff":
        raise PermissionError("review receipt is not bound to a diff")
    if receipt.get("session_binding_digest") != session.get("binding_digest"):
        raise PermissionError("review session binding mismatch")
    if receipt.get("output_binding_digest") != diff_output.get("output_binding_digest"):
        raise PermissionError("review output binding mismatch")
    if receipt.get("content_digest") != diff_output.get("content_digest"):
        raise PermissionError("review content binding mismatch")

    payload = {key: receipt[key] for key in required if key != "review_binding_digest"}
    if receipt.get("review_binding_digest") != _digest(payload):
        raise ValueError("review receipt was modified")
    return dict(receipt)
