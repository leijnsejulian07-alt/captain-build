import unittest

from promotion_revocation_epoch import (
    InMemoryPromotionEpochStore,
    assert_receipt_epoch_current,
    bind_receipt_epoch,
)


class PromotionRevocationEpochTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryPromotionEpochStore()
        self.scope = dict(chat_id="chat-a", project_id="project-a", repo_scope_hash="a" * 64)

    def test_current_epoch_receipt_is_accepted(self):
        snap = self.store.snapshot(**self.scope)
        receipt = bind_receipt_epoch({"receipt_id": "vr-1"}, snap)
        assert_receipt_epoch_current(receipt, self.store.snapshot(**self.scope))

    def test_rotation_immediately_invalidates_existing_receipt(self):
        snap = self.store.snapshot(**self.scope)
        receipt = bind_receipt_epoch({"receipt_id": "vr-1"}, snap)
        self.store.rotate(**self.scope, expected_epoch=snap.epoch, reason="security_reset")
        with self.assertRaisesRegex(PermissionError, "stale"):
            assert_receipt_epoch_current(receipt, self.store.snapshot(**self.scope))

    def test_rotation_is_compare_and_swap(self):
        snap = self.store.snapshot(**self.scope)
        self.store.rotate(**self.scope, expected_epoch=snap.epoch, reason="manual")
        with self.assertRaisesRegex(PermissionError, "changed before rotation"):
            self.store.rotate(**self.scope, expected_epoch=snap.epoch, reason="manual")

    def test_other_project_does_not_share_epoch(self):
        snap_a = self.store.snapshot(**self.scope)
        receipt_a = bind_receipt_epoch({"receipt_id": "vr-1"}, snap_a)
        other = dict(self.scope, project_id="project-b")
        with self.assertRaisesRegex(PermissionError, "scope mismatch"):
            assert_receipt_epoch_current(receipt_a, self.store.snapshot(**other))

    def test_legacy_unbound_receipt_fails_closed(self):
        with self.assertRaisesRegex(PermissionError, "legacy receipt"):
            assert_receipt_epoch_current({"receipt_id": "legacy"}, self.store.snapshot(**self.scope))

    def test_partial_epoch_metadata_fails_closed(self):
        snap = self.store.snapshot(**self.scope)
        with self.assertRaises((PermissionError, ValueError)):
            assert_receipt_epoch_current({"security_scope_key": snap.scope_key}, snap)

    def test_invalid_rotation_reason_is_rejected(self):
        snap = self.store.snapshot(**self.scope)
        with self.assertRaisesRegex(ValueError, "revocation reason"):
            self.store.rotate(**self.scope, expected_epoch=snap.epoch, reason="ignore-policy")


if __name__ == "__main__":
    unittest.main()
