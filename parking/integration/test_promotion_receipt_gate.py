import unittest

from promotion_receipt_gate import consume_receipt, issue_receipt


class PromotionReceiptGateTests(unittest.TestCase):
    def base(self):
        row = issue_receipt(
            receipt_id="vr-1", chat_id="chat-a", project_id="project-a",
            repo_scope="C:/repo/a", session_id="session-a",
            runtime_generation="epoch-a", profile_id="default",
            worktree_fingerprint="tree-a", issued_at=1000, expires_at=1300,
            validation_status="pass")
        return {"vr-1": row}

    def consume(self, ledger=None, **overrides):
        kw = dict(receipt_id="vr-1", action="promote", chat_id="chat-a",
                  project_id="project-a", repo_scope="C:/repo/a",
                  session_id="session-a", runtime_generation="epoch-a",
                  profile_id="default", current_worktree_fingerprint="tree-a",
                  now=1100)
        kw.update(overrides)
        return consume_receipt(self.base() if ledger is None else ledger, **kw)

    def test_exact_scope_pass_consumes_once(self):
        ledger, public = self.consume()
        self.assertTrue(public["accepted"])
        self.assertTrue(ledger["vr-1"]["consumed"])
        with self.assertRaisesRegex(ValueError, "already consumed"):
            self.consume(ledger=ledger)

    def test_unknown_forged_handle_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown validation receipt"):
            self.consume(receipt_id="vr-forged")

    def test_scope_runtime_session_profile_are_bound(self):
        for key, value in (("chat_id", "chat-b"), ("project_id", "project-b"),
                           ("repo_scope", "C:/repo/b"), ("session_id", "session-b"),
                           ("runtime_generation", "epoch-b"), ("profile_id", "other")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.consume(**{key: value})

    def test_worktree_mutation_invalidates_receipt(self):
        with self.assertRaisesRegex(ValueError, "worktree mismatch"):
            self.consume(current_worktree_fingerprint="tree-after-edit")

    def test_expired_and_future_receipts_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "expired or not yet valid"):
            self.consume(now=1301)
        with self.assertRaisesRegex(ValueError, "expired or not yet valid"):
            self.consume(now=999)

    def test_only_passing_validation_can_issue(self):
        with self.assertRaisesRegex(ValueError, "only passing validation"):
            issue_receipt(receipt_id="vr-x", chat_id="c", project_id="p",
                          repo_scope="repo", session_id="s", runtime_generation="e",
                          profile_id="default", worktree_fingerprint="tree",
                          issued_at=1, expires_at=2, validation_status="fail")

    def test_ttl_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "ttl invalid"):
            issue_receipt(receipt_id="vr-x", chat_id="c", project_id="p",
                          repo_scope="repo", session_id="s", runtime_generation="e",
                          profile_id="default", worktree_fingerprint="tree",
                          issued_at=1, expires_at=5000, validation_status="pass")

    def test_action_allowlist(self):
        with self.assertRaisesRegex(ValueError, "unsupported promotion action"):
            self.consume(action="push-force")


if __name__ == "__main__":
    unittest.main()
