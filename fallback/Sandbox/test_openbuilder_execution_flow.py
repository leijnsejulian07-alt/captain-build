from dataclasses import replace
import pytest

from sandbox_session_policy import create_sandbox_lease
from builder_execution_receipt import create_build_receipt
from openbuilder_execution_flow import (
    OpenBuilderExecution,
    attach_verified_receipt,
    begin_build,
    begin_review,
    begin_tests,
    mark_preview_ready,
    promote,
    rollback,
)


def _lease(*, epoch=7, project="alpha", session="sbx-1"):
    return create_sandbox_lease(
        session_id=session,
        chat_id="chat-1",
        project_id=project,
        repo_scope="repo:owner/app",
        state_epoch=epoch,
        backend="local-test",
    )


def _auth(*, epoch=7, project="alpha"):
    return dict(
        chat_id="chat-1",
        project_id=project,
        repo_scope="repo:owner/app",
        state_epoch=epoch,
    )


def _receipt(lease, *, tests="passed", review="passed"):
    return create_build_receipt(
        lease,
        execution_id="exec-1",
        base_revision="abc123",
        result_revision="def456",
        diff_bytes=b"diff --git a/app.py b/app.py\n+safe\n",
        test_status=tests,
        review_status=review,
        rollback_ref="checkpoint:abc123",
    )


def _reviewing(lease=None):
    execution = OpenBuilderExecution(lease or _lease())
    execution = begin_build(execution, **_auth())
    execution = begin_tests(execution, **_auth())
    return begin_review(execution, **_auth())


def test_happy_path_requires_build_test_review_preview_before_promote():
    lease = _lease()
    execution = _reviewing(lease)
    execution = attach_verified_receipt(execution, _receipt(lease), **_auth())
    execution = mark_preview_ready(execution, preview_ref="preview:exec-1", **_auth())
    execution = promote(execution, **_auth())
    assert execution.phase == "promoted"


def test_cannot_skip_phases_or_promote_without_preview():
    execution = OpenBuilderExecution(_lease())
    with pytest.raises(PermissionError):
        begin_tests(execution, **_auth())

    execution = _reviewing()
    with pytest.raises(PermissionError):
        promote(execution, **_auth())


def test_failed_test_or_review_cannot_reach_preview():
    for tests, review in (("failed", "passed"), ("passed", "failed")):
        lease = _lease()
        execution = _reviewing(lease)
        with pytest.raises(PermissionError):
            attach_verified_receipt(
                execution,
                _receipt(lease, tests=tests, review=review),
                **_auth(),
            )


def test_stale_epoch_and_cross_project_are_denied_at_every_control_point():
    execution = OpenBuilderExecution(_lease())
    with pytest.raises(PermissionError):
        begin_build(execution, **_auth(epoch=8))
    with pytest.raises(PermissionError):
        begin_build(execution, **_auth(project="beta"))


def test_receipt_from_different_sandbox_session_is_denied():
    execution = _reviewing(_lease(session="sbx-1"))
    other = _lease(session="sbx-2")
    receipt = _receipt(other)
    with pytest.raises(PermissionError):
        attach_verified_receipt(execution, receipt, **_auth())


def test_tampered_receipt_scope_is_denied():
    lease = _lease()
    execution = _reviewing(lease)
    receipt = replace(_receipt(lease), scope_digest="0" * 64)
    with pytest.raises(PermissionError):
        attach_verified_receipt(execution, receipt, **_auth())


def test_preview_ref_is_required_and_not_multiline():
    lease = _lease()
    execution = attach_verified_receipt(_reviewing(lease), _receipt(lease), **_auth())
    with pytest.raises(ValueError):
        mark_preview_ready(execution, preview_ref="", **_auth())
    with pytest.raises(ValueError):
        mark_preview_ready(execution, preview_ref="preview:ok\nSECRET=x", **_auth())


def test_rollback_is_available_before_promotion_and_terminal_afterward():
    execution = begin_build(OpenBuilderExecution(_lease()), **_auth())
    execution = rollback(execution, **_auth())
    assert execution.phase == "rolled_back"
    with pytest.raises(PermissionError):
        begin_tests(execution, **_auth())
