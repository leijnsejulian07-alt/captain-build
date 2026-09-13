from __future__ import annotations

import hashlib
import json
import re
from typing import Mapping

from parking.integration.builder_output_scope import authorize_builder_output
from parking.integration.builder_session_contract import authorize_builder_action

SCHEMA_VERSION = 1
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def issue_review_receipt(
    *,
    diff_output: Mapping[str, object],
    session: Mapping[str, object],
    scanner_name: str,
    scanner_version: str,
    scan_digest: str,
    finding_count: int,
) -> dict[str, object]:
    """Bind a secret-scan result to an exact builder diff without storing diff content."""
    if diff_output.get("kind") != "diff":
        raise ValueError("review gate requires a diff output")
    if not isinstance(scanner_name, str) or not _NAME_RE.fullmatch(scanner_name):
        raise ValueError("invalid scanner name")
    if not isinstance(scanner_version, str) or not _NAME_RE.fullmatch(scanner_version):
        raise ValueError("invalid scanner version")
    if not isinstance(scan_digest, str) or not _DIGEST_RE.fullmatch(scan_digest):
        raise ValueError("invalid scan digest")
    if isinstance(finding_count, bool) or not isinstance(finding_count, int) or finding_count < 0:
        raise ValueError("invalid finding count")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "session_binding_digest": session.get("binding_digest"),
        "output_binding_digest": diff_output.get("output_binding_digest"),
        "content_digest": diff_output.get("content_digest"),
        "scanner_name": scanner_name,
        "scanner_version": scanner_version,
        "scan_digest": scan_digest,
        "finding_count": finding_count,
        "apply_blocked": finding_count > 0,
    }
    for key in ("session_binding_digest", "output_binding_digest", "content_digest"):
        value = payload[key]
        if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
            raise ValueError(f"invalid {key}")
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
    """Fail closed unless the exact current clean diff has explicit apply approval."""
    required = {
        "schema_version", "session_binding_digest", "output_binding_digest",
        "content_digest", "scanner_name", "scanner_version", "scan_digest",
        "finding_count", "apply_blocked", "review_binding_digest",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != required:
        raise ValueError("invalid review receipt schema")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported review receipt schema")
    if explicit_approval is not True:
        raise PermissionError("explicit review approval required")
    if receipt.get("apply_blocked") is not False or receipt.get("finding_count") != 0:
        raise PermissionError("apply blocked by scan findings")

    authorized = authorize_builder_output(
        diff_output, session=session, chat_id=chat_id, project_id=project_id,
        repo_scope=repo_scope, session_id=session_id, repo_head=repo_head,
        worktree_digest=worktree_digest, state_epoch=state_epoch, now=now,
    )
    if authorized.get("kind") != "diff":
        raise PermissionError("review receipt is not bound to a diff")

    authorize_builder_action(
        session, chat_id=chat_id, project_id=project_id, repo_scope=repo_scope,
        session_id=session_id, repo_head=repo_head, worktree_digest=worktree_digest,
        state_epoch=state_epoch, capability="diff_write", now=now,
    )

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
