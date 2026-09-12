from dataclasses import replace
import pytest

from sandbox_session_policy import create_sandbox_lease
from builder_execution_receipt import (
    assert_receipt_access,
    create_build_receipt,
    require_promotion_ready,
)


def _lease(epoch=3, project="alpha"):
    return create_sandbox_lease(
        session_id="sbx-1",
        chat_id="chat-1",
        project_id=project,
        repo_scope="repo:owner/app",
        state_epoch=epoch,
        backend="local-test",
    )


def _receipt(lease=None, **overrides):
    lease = lease or _lease()
    args = dict(
        execution_id="exec-1",
        base_revision="abc123",
        result_revision="def456",
        diff_bytes=b"diff --git a/a b/a\n+safe\n",
        test_status="passed",
        review_status="passed",
        rollback_ref="checkpoint:abc123",
    )
    args.update(overrides)
    return create_build_receipt(lease, **args)


def test_happy_path_is_promotion_ready():
    receipt = _receipt()
    assert receipt.promotable is True
    require_promotion_ready(receipt)


def test_failed_or_skipped_test_is_not_promotable():
    for status in ("failed", "skipped"):
        receipt = _receipt(test_status=status)
        assert receipt.promotable is False
        with pytest.raises(PermissionError):
            require_promotion_ready(receipt)


def test_failed_or_skipped_review_is_not_promotable():
    for status in ("failed", "skipped"):
        receipt = _receipt(review_status=status)
        assert receipt.promotable is False
        with pytest.raises(PermissionError):
            require_promotion_ready(receipt)


def test_stale_epoch_is_denied():
    receipt = _receipt()
    with pytest.raises(PermissionError):
        assert_receipt_access(
            receipt,
            chat_id="chat-1",
            project_id="alpha",
            repo_scope="repo:owner/app",
            state_epoch=4,
        )


def test_cross_project_is_denied():
    receipt = _receipt()
    with pytest.raises(PermissionError):
        assert_receipt_access(
            receipt,
            chat_id="chat-1",
            project_id="beta",
            repo_scope="repo:owner/app",
            state_epoch=3,
        )


def test_cross_repo_is_denied():
    receipt = _receipt()
    with pytest.raises(PermissionError):
        assert_receipt_access(
            receipt,
            chat_id="chat-1",
            project_id="alpha",
            repo_scope="repo:owner/other",
            state_epoch=3,
        )


def test_tampered_scope_digest_is_denied_at_creation():
    lease = replace(_lease(), scope_digest="0" * 64)
    with pytest.raises(PermissionError):
        _receipt(lease)


def test_tampered_receipt_cannot_be_promoted():
    receipt = replace(_receipt(), promotable=True, test_status="failed")
    with pytest.raises(PermissionError):
        require_promotion_ready(receipt)


def test_empty_diff_and_same_revision_are_denied():
    with pytest.raises(ValueError):
        _receipt(diff_bytes=b"")
    with pytest.raises(ValueError):
        _receipt(result_revision="abc123")


def test_diff_contents_are_not_persisted():
    secret = b"API_KEY=super-secret-value"
    receipt = _receipt(diff_bytes=secret)
    assert not hasattr(receipt, "diff_bytes")
    assert "super-secret-value" not in repr(receipt)
