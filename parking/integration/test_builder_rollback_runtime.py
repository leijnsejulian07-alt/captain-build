from __future__ import annotations

import copy
import hashlib
import unittest

from parking.integration.builder_mutation_receipt import issue_builder_mutation_receipt
from parking.integration.builder_rollback_checkpoint import issue_builder_rollback_checkpoint
from parking.integration.builder_rollback_runtime import BuilderRollbackRuntime


def d(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


class BuilderRollbackRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scope = dict(chat_id="chat-a", project_id="project-a", repo_scope="repo-a")
        self.now = "2026-09-13T07:00:00Z"
        self.pre_head = "1" * 40
        self.post_head = "2" * 40
        self.pre_worktree = d("pre-worktree")
        self.post_worktree = d("post-worktree")
        self.pre_state = d("pre-state")
        self.post_state = d("post-state")
        self.source_action_binding = d("source-action")
        self.session_binding = d("session")
        self.context_binding = d("context")
        self.checkpoint = issue_builder_rollback_checkpoint(
            **self.scope,
            checkpoint_id="cp-1",
            source_request_id="req-1",
            source_action="files",
            source_action_binding=self.source_action_binding,
            session_binding=self.session_binding,
            context_binding=self.context_binding,
            target_git_head=self.pre_head,
            target_worktree_digest=self.pre_worktree,
            target_state_digest=self.pre_state,
            target_snapshot_digest=d("snapshot"),
            expected_current_git_head=self.post_head,
            expected_current_worktree_digest=self.post_worktree,
            expected_current_state_digest=self.post_state,
            created_at="2026-09-13T06:59:00Z",
        )
        self.receipt = issue_builder_mutation_receipt(
            mutation_id="mut-1",
            source_request_id="req-1",
            **self.scope,
            state_epoch=8,
            builder_session_id="builder-a",
            revision=3,
            artifact_digest=d("artifact"),
            review_binding_digest=d("review"),
            handle_scope_digest=d("handle"),
            pre_git_head=self.pre_head,
            pre_worktree_digest=self.pre_worktree,
            pre_state_digest=self.pre_state,
            post_git_head=self.post_head,
            post_worktree_digest=self.post_worktree,
            post_state_digest=self.post_state,
            rollback_checkpoint_binding=self.checkpoint["binding_digest"],
            created_at="2026-09-13T06:59:30Z",
        )

    def kwargs(self):
        return dict(
            mutation_receipt=self.receipt,
            rollback_checkpoint=self.checkpoint,
            mutation_id="mut-1",
            source_request_id="req-1",
            **self.scope,
            state_epoch=8,
            builder_session_id="builder-a",
            revision=3,
            artifact_digest=d("artifact"),
            review_binding_digest=d("review"),
            handle_scope_digest=d("handle"),
            checkpoint_id="cp-1",
            source_action_binding=self.source_action_binding,
            session_binding=self.session_binding,
            context_binding=self.context_binding,
            current_git_head=self.post_head,
            current_worktree_digest=self.post_worktree,
            current_state_digest=self.post_state,
            now=self.now,
            approved=True,
        )

    def test_exact_rollback_once(self):
        runtime = BuilderRollbackRuntime()
        calls = []
        result = runtime.execute(**self.kwargs(), apply_rollback=lambda cp: calls.append(cp["target_state_digest"]) or "ok")
        self.assertEqual(result, "ok")
        self.assertEqual(calls, [self.pre_state])
        with self.assertRaises(PermissionError):
            runtime.execute(**self.kwargs(), apply_rollback=lambda cp: "replayed")

    def test_requires_explicit_approval(self):
        runtime = BuilderRollbackRuntime()
        kw = self.kwargs()
        kw["approved"] = False
        with self.assertRaises(PermissionError):
            runtime.execute(**kw, apply_rollback=lambda cp: "bad")

    def test_cross_project_fails_closed(self):
        runtime = BuilderRollbackRuntime()
        kw = self.kwargs()
        kw["project_id"] = "project-b"
        with self.assertRaises(PermissionError):
            runtime.execute(**kw, apply_rollback=lambda cp: "bad")

    def test_target_must_equal_receipt_pre_state(self):
        runtime = BuilderRollbackRuntime()
        cp = issue_builder_rollback_checkpoint(
            **self.scope,
            checkpoint_id="cp-2",
            source_request_id="req-1",
            source_action="files",
            source_action_binding=self.source_action_binding,
            session_binding=self.session_binding,
            context_binding=self.context_binding,
            target_git_head="3" * 40,
            target_worktree_digest=d("wrong-pre-worktree"),
            target_state_digest=d("wrong-pre-state"),
            target_snapshot_digest=d("snapshot2"),
            expected_current_git_head=self.post_head,
            expected_current_worktree_digest=self.post_worktree,
            expected_current_state_digest=self.post_state,
            created_at="2026-09-13T06:59:00Z",
        )
        receipt = issue_builder_mutation_receipt(
            mutation_id="mut-1", source_request_id="req-1", **self.scope, state_epoch=8,
            builder_session_id="builder-a", revision=3, artifact_digest=d("artifact"),
            review_binding_digest=d("review"), handle_scope_digest=d("handle"),
            pre_git_head=self.pre_head, pre_worktree_digest=self.pre_worktree, pre_state_digest=self.pre_state,
            post_git_head=self.post_head, post_worktree_digest=self.post_worktree, post_state_digest=self.post_state,
            rollback_checkpoint_binding=cp["binding_digest"], created_at="2026-09-13T06:59:30Z",
        )
        kw = self.kwargs()
        kw.update(mutation_receipt=receipt, rollback_checkpoint=cp, checkpoint_id="cp-2")
        with self.assertRaises(PermissionError):
            runtime.execute(**kw, apply_rollback=lambda cp: "bad")

    def test_current_state_must_still_equal_receipt_post_state(self):
        runtime = BuilderRollbackRuntime()
        kw = self.kwargs()
        kw["current_state_digest"] = d("drifted")
        with self.assertRaises(PermissionError):
            runtime.execute(**kw, apply_rollback=lambda cp: "bad")

    def test_failed_rollback_burns_authority(self):
        runtime = BuilderRollbackRuntime()
        with self.assertRaises(RuntimeError):
            runtime.execute(**self.kwargs(), apply_rollback=lambda cp: (_ for _ in ()).throw(RuntimeError("disk failure")))
        with self.assertRaises(PermissionError):
            runtime.execute(**self.kwargs(), apply_rollback=lambda cp: "replay")

    def test_tampered_checkpoint_is_rejected(self):
        runtime = BuilderRollbackRuntime()
        cp = copy.deepcopy(self.checkpoint)
        cp["target_state_digest"] = d("tampered")
        kw = self.kwargs()
        kw["rollback_checkpoint"] = cp
        with self.assertRaises((ValueError, PermissionError)):
            runtime.execute(**kw, apply_rollback=lambda cp: "bad")


if __name__ == "__main__":
    unittest.main()
