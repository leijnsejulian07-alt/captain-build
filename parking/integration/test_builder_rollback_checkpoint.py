from __future__ import annotations

import copy
import unittest

from parking.integration.builder_rollback_checkpoint import (
    issue_builder_rollback_checkpoint,
    validate_builder_rollback_checkpoint,
)


D1 = "1" * 64
D2 = "2" * 64
D3 = "3" * 64
D4 = "4" * 64
D5 = "5" * 64
D6 = "6" * 64
HEAD1 = "a" * 40
HEAD2 = "b" * 40


class BuilderRollbackCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kwargs = {
            "chat_id": "chat-1",
            "project_id": "project-a",
            "repo_scope": "owner/repo#feature/x",
            "checkpoint_id": "checkpoint-1",
            "source_request_id": "request-1",
            "source_action": "files",
            "source_action_binding": D1,
            "session_binding": D2,
            "context_binding": D3,
            "target_git_head": HEAD1,
            "target_worktree_digest": D4,
            "target_state_digest": D5,
            "target_snapshot_digest": D6,
            "expected_current_git_head": HEAD2,
            "expected_current_worktree_digest": D6,
            "expected_current_state_digest": D4,
            "created_at": "2026-09-02T16:00:00Z",
        }
        self.checkpoint = issue_builder_rollback_checkpoint(**self.kwargs)
        self.validate = {
            "chat_id": "chat-1",
            "project_id": "project-a",
            "repo_scope": "owner/repo#feature/x",
            "checkpoint_id": "checkpoint-1",
            "source_request_id": "request-1",
            "source_action_binding": D1,
            "session_binding": D2,
            "context_binding": D3,
            "current_git_head": HEAD2,
            "current_worktree_digest": D6,
            "current_state_digest": D4,
            "now": "2026-09-02T17:00:00Z",
        }

    def test_round_trip(self) -> None:
        restored = validate_builder_rollback_checkpoint(self.checkpoint, **self.validate)
        self.assertEqual(restored["target_git_head"], HEAD1)
        self.assertEqual(restored["target_snapshot_digest"], D6)

    def test_cross_project_replay_fails_closed(self) -> None:
        args = dict(self.validate, project_id="project-b")
        with self.assertRaises(PermissionError):
            validate_builder_rollback_checkpoint(self.checkpoint, **args)

    def test_wrong_session_or_context_fails_closed(self) -> None:
        for field in ("session_binding", "context_binding"):
            args = dict(self.validate, **{field: "9" * 64})
            with self.subTest(field=field), self.assertRaises(PermissionError):
                validate_builder_rollback_checkpoint(self.checkpoint, **args)

    def test_rollback_after_additional_builder_change_fails_closed(self) -> None:
        args = dict(self.validate, current_state_digest="9" * 64)
        with self.assertRaises(PermissionError):
            validate_builder_rollback_checkpoint(self.checkpoint, **args)

    def test_changed_worktree_or_head_fails_closed(self) -> None:
        cases = {
            "current_git_head": "c" * 40,
            "current_worktree_digest": "9" * 64,
        }
        for field, value in cases.items():
            args = dict(self.validate, **{field: value})
            with self.subTest(field=field), self.assertRaises(PermissionError):
                validate_builder_rollback_checkpoint(self.checkpoint, **args)

    def test_tampering_fails_closed(self) -> None:
        modified = copy.deepcopy(self.checkpoint)
        modified["target_snapshot_digest"] = "9" * 64
        with self.assertRaises(ValueError):
            validate_builder_rollback_checkpoint(modified, **self.validate)

    def test_unknown_or_secret_field_fails_closed(self) -> None:
        for field in ("extra", "token"):
            modified = copy.deepcopy(self.checkpoint)
            modified[field] = "should-not-persist"
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_builder_rollback_checkpoint(modified, **self.validate)

    def test_future_and_stale_checkpoint_fail_closed(self) -> None:
        with self.assertRaises(PermissionError):
            validate_builder_rollback_checkpoint(
                self.checkpoint, **dict(self.validate, now="2026-09-02T15:59:59Z")
            )
        with self.assertRaises(PermissionError):
            validate_builder_rollback_checkpoint(
                self.checkpoint, **dict(self.validate, now="2026-09-10T16:00:01Z")
            )

    def test_noop_checkpoint_is_rejected(self) -> None:
        args = dict(
            self.kwargs,
            expected_current_git_head=HEAD1,
            expected_current_worktree_digest=D4,
            expected_current_state_digest=D5,
        )
        with self.assertRaises(ValueError):
            issue_builder_rollback_checkpoint(**args)

    def test_unsupported_source_action_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            issue_builder_rollback_checkpoint(**dict(self.kwargs, source_action="console"))


if __name__ == "__main__":
    unittest.main()
