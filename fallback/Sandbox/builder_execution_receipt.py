from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

_ALLOWED_STATUSES = {"passed", "failed", "skipped"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True)
class BuildExecutionReceipt:
    execution_id: str
    sandbox_session_id: str
    chat_id: str
    project_id: str
    repo_scope: str
    state_epoch: int
    scope_digest: str
    base_revision: str
    result_revision: str
    diff_digest: str
    test_status: str
    review_status: str
    rollback_ref: str
    promotable: bool


def _digest_scope(chat_id: str, project_id: str, repo_scope: str, state_epoch: int) -> str:
    return sha256(f"{chat_id}\n{project_id}\n{repo_scope}\n{state_epoch}".encode()).hexdigest()


def _clean_id(name: str, value: str) -> str:
    value = (value or "").strip()
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _clean_text(name: str, value: str) -> str:
    value = (value or "").strip()
    if not value or "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError(f"invalid {name}")
    return value


def create_build_receipt(
    lease,
    *,
    execution_id: str,
    base_revision: str,
    result_revision: str,
    diff_bytes: bytes,
    test_status: str,
    review_status: str,
    rollback_ref: str,
) -> BuildExecutionReceipt:
    execution_id = _clean_id("execution_id", execution_id)
    base_revision = _clean_text("base_revision", base_revision)
    result_revision = _clean_text("result_revision", result_revision)
    rollback_ref = _clean_text("rollback_ref", rollback_ref)
    if base_revision == result_revision:
        raise ValueError("result revision must differ from base revision")
    if not isinstance(diff_bytes, (bytes, bytearray)) or not diff_bytes:
        raise ValueError("diff_bytes must be non-empty bytes")
    if test_status not in _ALLOWED_STATUSES:
        raise ValueError("invalid test_status")
    if review_status not in _ALLOWED_STATUSES:
        raise ValueError("invalid review_status")

    expected_scope = _digest_scope(
        lease.chat_id, lease.project_id, lease.repo_scope, lease.state_epoch
    )
    if expected_scope != lease.scope_digest:
        raise PermissionError("sandbox lease scope digest is invalid")

    diff_digest = sha256(bytes(diff_bytes)).hexdigest()
    promotable = test_status == "passed" and review_status == "passed"
    return BuildExecutionReceipt(
        execution_id=execution_id,
        sandbox_session_id=lease.session_id,
        chat_id=lease.chat_id,
        project_id=lease.project_id,
        repo_scope=lease.repo_scope,
        state_epoch=lease.state_epoch,
        scope_digest=lease.scope_digest,
        base_revision=base_revision,
        result_revision=result_revision,
        diff_digest=diff_digest,
        test_status=test_status,
        review_status=review_status,
        rollback_ref=rollback_ref,
        promotable=promotable,
    )


def assert_receipt_access(
    receipt: BuildExecutionReceipt,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    state_epoch: int,
) -> None:
    expected = _digest_scope(chat_id.strip(), project_id.strip(), repo_scope.strip(), state_epoch)
    if (
        state_epoch != receipt.state_epoch
        or expected != receipt.scope_digest
        or chat_id != receipt.chat_id
        or project_id != receipt.project_id
        or repo_scope != receipt.repo_scope
    ):
        raise PermissionError("build receipt scope/epoch mismatch")


def require_promotion_ready(receipt: BuildExecutionReceipt) -> None:
    if not receipt.promotable:
        raise PermissionError("build output is not promotion-ready")
    if receipt.test_status != "passed" or receipt.review_status != "passed":
        raise PermissionError("build output failed test/review gate")
