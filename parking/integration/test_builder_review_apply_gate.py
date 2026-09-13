from __future__ import annotations

import hashlib
import unittest

from parking.integration.builder_output_scope import issue_builder_output
from parking.integration.builder_review_apply_gate import authorize_apply, issue_review_receipt
from parking.integration.builder_session_contract import issue_builder_session


class BuilderReviewApplyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scope = dict(chat_id="chat-a", project_id="project-a", repo_scope="repo://captain/a",
                          session_id="builder-1", repo_head="a" * 40,
                          worktree_digest="b" * 64, state_epoch=7)
        self.session = issue_builder_session(
            **self.scope, capabilities=["diff_read", "diff_write"],
            created_at="2026-09-13T00:00:00+00:00", expires_at="2026-09-13T01:00:00+00:00")
        digest = hashlib.sha256(b"candidate-diff").hexdigest()
        self.output = issue_builder_output(session=self.session, output_id="diff-1", kind="diff",
                                           revision=1, content_digest=digest)
        self.receipt = issue_review_receipt(
            diff_output=self.output, session=self.session, scanner_name="captain-scan",
            scanner_version="1.0.0", scan_digest="c" * 64, finding_count=0)

    def test_clean_current_review_requires_explicit_approval(self):
        row = authorize_apply(self.receipt, diff_output=self.output, session=self.session,
                              now="2026-09-13T00:30:00+00:00", explicit_approval=True, **self.scope)
        self.assertFalse(row["apply_blocked"])
        with self.assertRaises(PermissionError):
            authorize_apply(self.receipt, diff_output=self.output, session=self.session,
                            now="2026-09-13T00:30:00+00:00", explicit_approval=False, **self.scope)

    def test_findings_block_apply(self):
        blocked = issue_review_receipt(
            diff_output=self.output, session=self.session, scanner_name="captain-scan",
            scanner_version="1.0.0", scan_digest="d" * 64, finding_count=1)
        with self.assertRaises(PermissionError):
            authorize_apply(blocked, diff_output=self.output, session=self.session,
                            now="2026-09-13T00:30:00+00:00", explicit_approval=True, **self.scope)

    def test_read_only_session_cannot_apply(self):
        read_only = issue_builder_session(
            **self.scope, capabilities=["diff_read"],
            created_at="2026-09-13T00:00:00+00:00", expires_at="2026-09-13T01:00:00+00:00")
        output = issue_builder_output(session=read_only, output_id="diff-2", kind="diff", revision=1,
                                      content_digest=self.output["content_digest"])
        receipt = issue_review_receipt(diff_output=output, session=read_only, scanner_name="captain-scan",
                                       scanner_version="1.0.0", scan_digest="e" * 64, finding_count=0)
        with self.assertRaises(PermissionError):
            authorize_apply(receipt, diff_output=output, session=read_only,
                            now="2026-09-13T00:30:00+00:00", explicit_approval=True, **self.scope)

    def test_epoch_and_project_replay_fail_closed(self):
        for override in ({"state_epoch": 8}, {"project_id": "project-b"}):
            args = dict(self.scope); args.update(override)
            with self.assertRaises(PermissionError):
                authorize_apply(self.receipt, diff_output=self.output, session=self.session,
                                now="2026-09-13T00:30:00+00:00", explicit_approval=True, **args)

    def test_receipt_omits_raw_scope(self):
        text = repr(self.receipt)
        self.assertNotIn("chat-a", text)
        self.assertNotIn("project-a", text)
        self.assertNotIn("repo://captain/a", text)


if __name__ == "__main__":
    unittest.main()
