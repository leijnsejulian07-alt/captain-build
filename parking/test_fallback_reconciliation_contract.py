import unittest
from fallback_reconciliation_contract import FallbackCheckpoint, can_reconcile, transition

S1 = "1" * 40
S2 = "2" * 40


class ReconciliationContractTests(unittest.TestCase):
    def cp(self, **kw):
        base = dict(checkpoint_id="skills-v1", source_ref="pr-1", source_sha=S1,
                    repo_scope=r"C:\\AI\\Captain", local_base_sha=S2)
        base.update(kw)
        return FallbackCheckpoint.create(**base)

    def test_exact_scope_and_base_can_reconcile(self):
        self.assertTrue(can_reconcile(self.cp(), repo_scope=r"C:\\AI\\Captain",
                                      actual_local_base_sha=S2, completed=[]))

    def test_cross_repo_scope_denied(self):
        self.assertFalse(can_reconcile(self.cp(), repo_scope=r"C:\\AI\\Other",
                                       actual_local_base_sha=S2, completed=[]))

    def test_stale_local_base_denied(self):
        self.assertFalse(can_reconcile(self.cp(), repo_scope=r"C:\\AI\\Captain",
                                       actual_local_base_sha=S1, completed=[]))

    def test_dependency_must_be_completed(self):
        cp = self.cp(dependencies=("job-contract",))
        self.assertFalse(can_reconcile(cp, repo_scope=r"C:\\AI\\Captain",
                                       actual_local_base_sha=S2, completed=[]))
        self.assertTrue(can_reconcile(cp, repo_scope=r"C:\\AI\\Captain",
                                      actual_local_base_sha=S2, completed=["job-contract"]))

    def test_duplicate_or_self_dependency_rejected(self):
        with self.assertRaises(ValueError): self.cp(dependencies=("x", "x"))
        with self.assertRaises(ValueError): self.cp(dependencies=("skills-v1",))

    def test_path_like_ids_rejected(self):
        with self.assertRaises(ValueError): self.cp(checkpoint_id="../escape")
        with self.assertRaises(ValueError): self.cp(source_ref="refs/heads/main")

    def test_invalid_sha_rejected(self):
        with self.assertRaises(ValueError): self.cp(source_sha="main")

    def test_status_machine_is_monotonic(self):
        verified = transition(self.cp(), "verified")
        integrated = transition(verified, "integrated")
        self.assertEqual(integrated.status, "integrated")
        with self.assertRaises(ValueError): transition(integrated, "pending")

    def test_rejected_or_integrated_cannot_reconcile(self):
        rejected = transition(self.cp(), "rejected")
        self.assertFalse(can_reconcile(rejected, repo_scope=r"C:\\AI\\Captain",
                                       actual_local_base_sha=S2, completed=[]))


if __name__ == "__main__":
    unittest.main()
