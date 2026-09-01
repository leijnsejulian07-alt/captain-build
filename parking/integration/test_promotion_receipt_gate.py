import unittest

from promotion_receipt_gate import consume_receipt, issue_receipt


class PromotionReceiptGateTests(unittest.TestCase):
    def base(self, **overrides):
        kw = dict(
            receipt_id="vr-1", chat_id="chat-a", project_id="project-a",
            repo_scope="C:/repo/a", session_id="session-a",
            runtime_generation="epoch-a", profile_id="default",
            worktree_fingerprint="tree-a", issued_at=1000, expires_at=1300,
            validation_status="pass", authorized_action="promote")
        kw.update(overrides)
        row = issue_receipt(**kw)
        return {row["receipt_id"]: row}

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

    def test_action_is_bound_at_receipt_issue_time(self):
        approve_ledger = self.base(authorized_action="approve")
        with self.assertRaisesRegex(ValueError, "action mismatch"):
            self.consume(ledger=approve_ledger, action="merge")
        ledger, public = self.consume(ledger=approve_ledger, action="approve")
        self.assertEqual(public["action"], "approve")
        self.assertEqual(ledger["vr-1"]["consumed_action"], "approve")

    def test_legacy_unbound_receipt_fails_closed(self):
        ledger = self.base()
        ledger["vr-1"]["schema_version"] = 1
        ledger["vr-1"].pop("authorized_action")
        with self.assertRaisesRegex(ValueError, "invalid validation receipt"):
            self.consume(ledger=ledger)

    def test_malformed_or_extended_receipt_schema_fails_closed(self):
        ledger = self.base()
        ledger["vr-1"]["unexpected"] = "do-not-ignore"
        with self.assertRaisesRegex(ValueError, "invalid validation receipt schema"):
            self.consume(ledger=ledger)
        ledger = self.base()
        ledger["vr-1"].pop("profile_id")
        with self.assertRaisesRegex(ValueError, "invalid validation receipt schema"):
            self.consume(ledger=ledger)

    def test_inconsistent_unconsumed_state_fails_closed(self):
        ledger = self.base()
        ledger["vr-1"]["consumed_action"] = "promote"
        with self.assertRaisesRegex(ValueError, "already consumed or malformed"):
            self.consume(ledger=ledger)
        ledger = self.base()
        ledger["vr-1"]["consumed_at"] = 1099
        with self.assertRaisesRegex(ValueError, "already consumed or malformed"):
            self.consume(ledger=ledger)

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
                          issued_at=1, expires_at=2, validation_status="fail",
                          authorized_action="promote")

    def test_ttl_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "ttl invalid"):
            issue_receipt(receipt_id="vr-x", chat_id="c", project_id="p",
                          repo_scope="repo", session_id="s", runtime_generation="e",
                          profile_id="default", worktree_fingerprint="tree",
                          issued_at=1, expires_at=5000, validation_status="pass",
                          authorized_action="promote")

    def test_action_allowlist_applies_to_issue_and_consume(self):
        with self.assertRaisesRegex(ValueError, "unsupported promotion action"):
            self.base(authorized_action="push-force")
        with self.assertRaisesRegex(ValueError, "unsupported promotion action"):
            self.consume(action="push-force")


if __name__ == "__main__":
    unittest.main()
