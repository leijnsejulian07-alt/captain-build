import pytest

from builder_execution_receipt import create_build_receipt
from builder_pane_snapshot import assert_builder_pane_access, project_builder_pane
from openbuilder_execution_flow import (
    OpenBuilderExecution,
    attach_verified_receipt,
    begin_build,
    begin_review,
    begin_tests,
    mark_preview_ready,
)
from sandbox_session_policy import create_sandbox_lease

AUTH = dict(chat_id="chat-a", project_id="project-a", repo_scope="repo-a", state_epoch=7)


def _execution():
    lease = create_sandbox_lease(session_id="sandbox-a", **AUTH, backend="local-test")
    execution = OpenBuilderExecution(lease=lease)
    execution = begin_build(execution, **AUTH)
    execution = begin_tests(execution, **AUTH)
    execution = begin_review(execution, **AUTH)
    receipt = create_build_receipt(
        lease,
        execution_id="build-a",
        base_revision="abc",
        result_revision="def",
        diff_bytes=b"safe-diff",
        test_status="passed",
        review_status="passed",
        rollback_ref="rollback/build-a",
    )
    execution = attach_verified_receipt(execution, receipt, **AUTH)
    return mark_preview_ready(execution, preview_ref="preview/build-a", **AUTH)


def test_projection_exposes_only_refs_and_actions():
    pane = project_builder_pane(
        _execution(),
        **AUTH,
        active_tab="preview",
        diff_ref="diff/build-a",
        console_ref="console/build-a",
    )
    assert pane.preview_ref == "preview/build-a"
    assert pane.diff_ref == "diff/build-a"
    assert pane.console_ref == "console/build-a"
    assert pane.rollback_ref == "rollback/build-a"
    assert pane.can_promote is True
    assert pane.can_rollback is True


def test_stale_epoch_is_denied():
    with pytest.raises(PermissionError):
        project_builder_pane(_execution(), **{**AUTH, "state_epoch": 8})


def test_cross_project_and_repo_are_denied():
    with pytest.raises(PermissionError):
        project_builder_pane(_execution(), **{**AUTH, "project_id": "project-b"})
    with pytest.raises(PermissionError):
        project_builder_pane(_execution(), **{**AUTH, "repo_scope": "repo-b"})


def test_snapshot_access_is_epoch_and_scope_bound():
    pane = project_builder_pane(_execution(), **AUTH)
    assert_builder_pane_access(pane, **AUTH)
    with pytest.raises(PermissionError):
        assert_builder_pane_access(pane, **{**AUTH, "chat_id": "chat-b"})
    with pytest.raises(PermissionError):
        assert_builder_pane_access(pane, **{**AUTH, "state_epoch": 8})


def test_raw_multiline_or_oversized_refs_are_rejected():
    execution = _execution()
    with pytest.raises(ValueError):
        project_builder_pane(execution, **AUTH, console_ref="secret\nraw-output")
    with pytest.raises(ValueError):
        project_builder_pane(execution, **AUTH, diff_ref="x" * 513)


def test_unknown_tab_is_rejected():
    with pytest.raises(ValueError):
        project_builder_pane(_execution(), **AUTH, active_tab="terminal")
