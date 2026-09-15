from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, TypeVar

from parking.integration.builder_review_apply_gate import authorize_apply

_T = TypeVar("_T")


class HandleStore(Protocol):
    def consume(
        self,
        handle_id: str,
        *,
        expected_kind: str,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        current_epoch: int,
        builder_session_id: str,
        exact_revision: int,
        expected_artifact_digest: str,
        now: int | None = None,
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class AppliedMutation:
    revision: int
    artifact_digest: str
    review_binding_digest: str
    handle_scope_digest: str


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def apply_reviewed_diff(
    *,
    handle_store: HandleStore,
    handle_id: str,
    diff_body: bytes,
    receipt: Mapping[str, object],
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
    now_unix: int,
    explicit_approval: bool,
    apply_fn: Callable[[bytes], _T],
) -> tuple[_T, AppliedMutation]:
    """Apply exactly the diff that was scanned and approved, once.

    This is the mutation boundary that joins Captain's existing review receipt with
    the single-use opaque output handle. It intentionally consumes the handle before
    invoking ``apply_fn``: a failed mutation requires a fresh diff/review/approval
    instead of silently reusing old authority.
    """
    if not isinstance(diff_body, bytes):
        raise TypeError("diff_body must be bytes")
    if not callable(apply_fn):
        raise TypeError("apply_fn must be callable")

    reviewed = authorize_apply(
        receipt,
        diff_output=diff_output,
        session=session,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        session_id=session_id,
        repo_head=repo_head,
        worktree_digest=worktree_digest,
        state_epoch=state_epoch,
        now=now,
        explicit_approval=explicit_approval,
    )

    revision = diff_output.get("revision")
    expected_digest = diff_output.get("content_digest")
    review_digest = reviewed.get("review_binding_digest")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("invalid reviewed revision")
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        raise ValueError("invalid reviewed content digest")
    if not isinstance(review_digest, str) or len(review_digest) != 64:
        raise ValueError("invalid review binding digest")

    actual_digest = _sha256(diff_body)
    if not hmac.compare_digest(actual_digest, expected_digest):
        raise PermissionError("diff body changed after review")

    redeemed = handle_store.consume(
        handle_id,
        expected_kind="diff",
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        current_epoch=state_epoch,
        builder_session_id=session_id,
        exact_revision=revision,
        expected_artifact_digest=expected_digest,
        now=now_unix,
    )
    handle_digest = redeemed.get("artifact_digest")
    scope_digest = redeemed.get("scope_digest")
    if not isinstance(handle_digest, str) or not hmac.compare_digest(handle_digest, expected_digest):
        raise PermissionError("redeemed handle artifact mismatch")
    if not isinstance(scope_digest, str) or len(scope_digest) != 64:
        raise ValueError("invalid redeemed handle scope")

    result = apply_fn(diff_body)
    return result, AppliedMutation(
        revision=revision,
        artifact_digest=expected_digest,
        review_binding_digest=review_digest,
        handle_scope_digest=scope_digest,
    )
