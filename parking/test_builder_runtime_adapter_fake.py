import unittest
from builder_runtime_adapter_fake import BuilderScope, FakeBuilderRuntimeAdapter, ScopeError


class BuilderRuntimeIsolationTests(unittest.TestCase):
    def setUp(self):
        self.rt = FakeBuilderRuntimeAdapter()
        self.a = BuilderScope("chat-a", "project-a", "repo-a", "session-a", 7)
        self.rt.create(self.a)

    def mutate(self, **kw):
        d = self.a.__dict__.copy(); d.update(kw); return BuilderScope(**d)

    def assert_denied(self, scope):
        for op in (self.rt.inspect, self.rt.checkpoint, self.rt.preview):
            with self.assertRaises(ScopeError): op(scope)

    def test_each_wall_is_authoritative(self):
        self.assert_denied(self.mutate(chat_id="chat-b"))
        self.assert_denied(self.mutate(project_id="project-b"))
        self.assert_denied(self.mutate(repo_scope="repo-b"))
        self.assert_denied(self.mutate(state_epoch=8))
        self.assert_denied(self.mutate(builder_session_id="missing"))

    def test_stale_epoch_cannot_inspect_preview_checkpoint_or_rollback(self):
        cp = self.rt.checkpoint(self.a)
        self.rt.preview(self.a)
        stale = self.mutate(state_epoch=8)
        self.assert_denied(stale)
        with self.assertRaises(ScopeError): self.rt.rollback(stale, cp)

    def test_native_session_id_does_not_confer_authority(self):
        attacker = BuilderScope("other", "other", "other", "session-a", 7)
        with self.assertRaises(ScopeError): self.rt.create(attacker)
        self.assert_denied(attacker)

    def test_rollback_must_be_in_owned_history(self):
        self.assertEqual(self.rt.checkpoint(self.a), 1)
        with self.assertRaises(ScopeError): self.rt.rollback(self.a, 2)
        with self.assertRaises(ScopeError): self.rt.rollback(self.a, -1)
        with self.assertRaises(ScopeError): self.rt.rollback(self.a, True)
        self.assertEqual(self.rt.rollback(self.a, 0), 0)

    def test_stop_revokes_preview_and_session_access(self):
        self.rt.preview(self.a)
        self.rt.stop(self.a)
        self.assert_denied(self.a)

    def test_malformed_scope_fails_closed(self):
        for bad in (
            self.mutate(chat_id=""), self.mutate(project_id=" "),
            self.mutate(repo_scope=""), self.mutate(builder_session_id=""),
            self.mutate(state_epoch=-1), self.mutate(state_epoch=True),
        ):
            self.assert_denied(bad)


if __name__ == "__main__":
    unittest.main()
