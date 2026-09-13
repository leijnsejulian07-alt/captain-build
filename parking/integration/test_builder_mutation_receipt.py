from __future__ import annotations

import copy
import unittest

from parking.integration.builder_mutation_receipt import (
    issue_builder_mutation_receipt,
    validate_builder_mutation_receipt,
)

_A = "a" * 64
_B = "b" * 64
_C = "c" * 64
_HEAD = "1" * 40


class BuilderMutationReceiptTests(unittest.TestCase):
    def _receipt(self) -> dict[str, object]:
        return issue_builder_mutation_receipt(
            mutation_id="mutation-1",
            source_request_id="request-1",
            chat_id="chat-a",
            project_id="project-a",
            repo_scope="repo-a",
            state_epoch=7,
            builder_session_id="session-a",
            revision=4,
            artifact_digest=_A,
            review_binding_digest=_B,
            handle_scope_digest=_C,
            pre_git_head=_HEAD,
            pre_worktree_digest=_A,
            pre_state_digest=_B,
            post_git_head=_HEAD,
            post_worktree_digest=_C,
            post_state_digest=_A,
            rollback_checkpoint_binding=_B,
            created_at="2026-09-13T05:55:00Z",
        )

    def _validate(self, receipt: dict[str, object], **overrides: object) -> dict[str, object]:
        args: dict[str, object] = {
            "mutation_id": "mutation-1",
            "source_request_id": "request-1",
            "chat_id": "chat-a",
            "project_id": "project-a",
            "repo_scope": "repo-a",
            "state_epoch": 7,
            "builder_session_id": "session-a",
            "revision": 4,
            "artifact_digest": _A,
            "review_binding_digest": _B,
            "handle_scope_digest": _C,
            "current_git_head": _HEAD,
            "current_worktree_digest": _C,
            "current_state_digest": _A,
            "rollback_checkpoint_binding": _B,
            "now": "2026-09-13T06:00:00Z",
        }
        args.update(overrides)
        return validate_builder_mutation_receipt(receipt, **args)  # type: ignore[arg-type]

    def test_exact_lifecycle_validates(self) -> None:
        receipt = self._receipt()
        self.assertEqual(self._validate(receipt)["revision"], 4)

    def test_cross_project_replay_fails_closed(self) -> None:
        with self.assertRaises(PermissionError):
            self._validate(self._receipt(), project_id="project-b")

    def test_cross_builder_session_replay_fails_closed(self) -> None:
        with self.assertRaises(PermissionError):
            self._validate(self._receipt(), builder_session_id="session-b")

    def test_stale_epoch_fails_closed(self) -> None:
        with self.assertRaises(PermissionError):
            self._validate(self._receipt(), state_epoch=8)

    def test_wrong_rollback_checkpoint_fails_closed(self) -> None:
        with self.assertRaises(PermissionError):
            self._validate(self._receipt(), rollback_checkpoint_binding=_C)

    def test_post_state_drift_fails_closed(self) -> None:
        with self.assertRaises(PermissionError):
            self._validate(self._receipt(), current_worktree_digest=_B)

    def test_tampering_is_detected(self) -> None:
        receipt = copy.deepcopy(self._receipt())
        receipt["post_state_digest"] = _C
        with self.assertRaises((PermissionError, ValueError)):
            self._validate(receipt)

    def test_noop_mutation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            issue_builder_mutation_receipt(
                mutation_id="mutation-1",
                source_request_id="request-1",
                chat_id="chat-a",
                project_id="project-a",
                repo_scope="repo-a",
                state_epoch=7,
                builder_session_id="session-a",
                revision=4,
                artifact_digest=_A,
                review_binding_digest=_B,
                handle_scope_digest=_C,
                pre_git_head=_HEAD,
                pre_worktree_digest=_A,
                pre_state_digest=_B,
                post_git_head=_HEAD,
                post_worktree_digest=_A,
                post_state_digest=_B,
                rollback_checkpoint_binding=_B,
                created_at="2026-09-13T05:55:00Z",
            )

    def test_exported_receipt_does_not_expose_raw_scope(self) -> None:
        receipt = self._receipt()
        serialized = repr(receipt)
        for secret_scope_value in ("chat-a", "project-a", "repo-a", "session-a"):
            self.assertNotIn(secret_scope_value, serialized)


if __name__ == "__main__":
    unittest.main()
