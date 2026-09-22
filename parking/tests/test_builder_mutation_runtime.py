from __future__ import annotations

import hashlib
import unittest

from parking.integration.builder_mutation_runtime import apply_reviewed_diff
from parking.integration.builder_output_handles import BuilderOutputHandleStore
from parking.integration.builder_output_scope import issue_builder_output
from parking.integration.builder_review_apply_gate import issue_review_receipt
from parking.integration.builder_session_contract import issue_builder_session


class BuilderMutationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.chat_id = "chat1"
        self.project_id = "proj1"
        self.repo_scope = "owner/repo#main"
        self.session_id = "session1"
        self.repo_head = "1" * 40
        self.worktree_digest = "2" * 64
        self.epoch = 3
        self.now = "2026-09-13T05:00:00Z"
        self.now_unix = 1789275600
        self.body = b"diff --git a/a b/a\n+safe change\n"
        self.digest = hashlib.sha256(self.body).hexdigest()
        self.session = issue_builder_session(
            chat_id=self.chat_id,
            project_id=self.project_id,
            repo_scope=self.repo_scope,
            session_id=self.session_id,
            repo_head=self.repo_head,
            worktree_digest=self.worktree_digest,
            state_epoch=self.epoch,
            capabilities=["diff_read", "diff_write"],
            created_at="2026-09-13T04:55:00Z",
            expires_at="2026-09-13T06:00:00Z",
        )
        self.output = issue_builder_output(
            session=self.session,
            output_id="diff-7",
            kind="diff",
            revision=7,
            content_digest=self.digest,
        )
        self.receipt = issue_review_receipt(
            diff_output=self.output,
            session=self.session,
            scanner_name="captain-secret-scan",
            scanner_version="1.0",
            scan_digest="3" * 64,
            finding_count=0,
        )
        self.store = BuilderOutputHandleStore(b"x" * 32)
        self.handle = self.store.issue(
            kind="diff",
            chat_id=self.chat_id,
            project_id=self.project_id,
            repo_scope=self.repo_scope,
            epoch=self.epoch,
            builder_session_id=self.session_id,
            revision=7,
            artifact_digest=self.digest,
            ttl_seconds=900,
            now=self.now_unix,
        )
        self.applied = []

    def call(self, **overrides):
        args = dict(
            handle_store=self.store,
            handle_id=self.handle,
            diff_body=self.body,
            receipt=self.receipt,
            diff_output=self.output,
            session=self.session,
            chat_id=self.chat_id,
            project_id=self.project_id,
            repo_scope=self.repo_scope,
            session_id=self.session_id,
            repo_head=self.repo_head,
            worktree_digest=self.worktree_digest,
            state_epoch=self.epoch,
            now=self.now,
            now_unix=self.now_unix,
            explicit_approval=True,
            apply_fn=lambda body: self.applied.append(body) or "ok",
        )
        args.update(overrides)
        return apply_reviewed_diff(**args)

    def test_exact_reviewed_body_applies_once(self):
        result, audit = self.call()
        self.assertEqual(result, "ok")
        self.assertEqual(self.applied, [self.body])
        self.assertEqual(audit.revision, 7)
        self.assertEqual(audit.artifact_digest, self.digest)
        with self.assertRaises(PermissionError):
            self.call()

    def test_tampered_body_is_rejected_before_handle_consumption(self):
        with self.assertRaisesRegex(PermissionError, "changed after review"):
            self.call(diff_body=self.body + b"+tamper\n")
        self.assertEqual(self.applied, [])
        # A clean retry still succeeds because the tampered body never consumed authority.
        self.assertEqual(self.call()[0], "ok")

    def test_failed_mutation_burns_authority_and_requires_fresh_review(self):
        def fail(_body):
            raise RuntimeError("apply failed")
        with self.assertRaises(RuntimeError):
            self.call(apply_fn=fail)
        with self.assertRaises(PermissionError):
            self.call()

    def test_cross_epoch_replay_is_denied(self):
        with self.assertRaises(PermissionError):
            self.call(state_epoch=self.epoch + 1)
        self.assertEqual(self.applied, [])

    def test_missing_explicit_approval_is_denied_without_apply(self):
        with self.assertRaises(PermissionError):
            self.call(explicit_approval=False)
        self.assertEqual(self.applied, [])


if __name__ == "__main__":
    unittest.main()
