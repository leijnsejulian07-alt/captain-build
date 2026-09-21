import unittest
from builder_runtime_adapter_fake import (
    BuilderScope, FakeBuilderRuntimeAdapter, ScopeError,
    MAX_CHECKPOINTS, MAX_FILE_BYTES, MAX_LOG_EVENTS, MAX_SESSION_BYTES, MAX_SESSION_FILES,
)


class BuilderRuntimeIsolationTests(unittest.TestCase):
    def setUp(self):
        self.rt = FakeBuilderRuntimeAdapter()
        self.a = BuilderScope("chat-a", "project-a", "repo-a", "session-a", 7)
        self.rt.create(self.a)

    def mutate(self, **kw):
        d = self.a.__dict__.copy(); d.update(kw); return BuilderScope(**d)

    def assert_denied(self, scope):
        for op in (self.rt.inspect, self.rt.checkpoint, self.rt.preview, self.rt.diff, self.rt.logs, self.rt.list_files):
            with self.assertRaises(ScopeError): op(scope)
        with self.assertRaises(ScopeError): self.rt.read_file(scope, "src/app.py")
        with self.assertRaises(ScopeError): self.rt.write_file(scope, "src/app.py", "x")
        with self.assertRaises(ScopeError): self.rt.delete_file(scope, "src/app.py")
        with self.assertRaises(ScopeError): self.rt.run(scope, "test")

    def test_each_wall_is_authoritative(self):
        self.assert_denied(self.mutate(chat_id="chat-b"))
        self.assert_denied(self.mutate(project_id="project-b"))
        self.assert_denied(self.mutate(repo_scope="repo-b"))
        self.assert_denied(self.mutate(state_epoch=8))
        self.assert_denied(self.mutate(builder_session_id="missing"))

    def test_stale_epoch_cannot_access_any_builder_surface(self):
        self.rt.write_file(self.a, "src/app.py", "v1")
        cp = self.rt.checkpoint(self.a)
        self.rt.preview(self.a)
        stale = self.mutate(state_epoch=8)
        self.assert_denied(stale)
        with self.assertRaises(ScopeError): self.rt.rollback(stale, cp)

    def test_native_session_id_does_not_confer_authority(self):
        attacker = BuilderScope("other", "other", "other", "session-a", 7)
        with self.assertRaises(ScopeError): self.rt.create(attacker)
        self.assert_denied(attacker)

    def test_checkpoint_rollback_restores_files_and_logs(self):
        self.rt.write_file(self.a, "src/app.py", "v1")
        self.rt.run(self.a, "test-v1")
        cp = self.rt.checkpoint(self.a)
        self.rt.write_file(self.a, "src/app.py", "v2")
        self.rt.write_file(self.a, "src/new.py", "new")
        self.rt.run(self.a, "test-v2")
        self.assertEqual(self.rt.diff(self.a), {"src/app.py": "v2", "src/new.py": "new"})
        self.rt.rollback(self.a, cp)
        self.assertEqual(self.rt.read_file(self.a, "src/app.py"), "v1")
        with self.assertRaises(ScopeError): self.rt.read_file(self.a, "src/new.py")
        self.assertEqual(self.rt.logs(self.a), ("fake-run:accepted",))
        self.assertEqual(self.rt.diff(self.a), {})

    def test_run_never_persists_raw_command_or_secrets(self):
        secret = "sk-test-super-secret"
        command = f"OPENAI_API_KEY={secret} npm test -- --token={secret}"
        self.assertEqual(self.rt.run(self.a, command), "fake-run:accepted")
        persisted = "\n".join(self.rt.logs(self.a))
        self.assertNotIn(secret, persisted)
        self.assertNotIn("OPENAI_API_KEY", persisted)
        self.assertNotIn("npm test", persisted)
        self.assertEqual(persisted, "fake-run:accepted")

    def test_delete_is_diffed_and_rollback_restores_file(self):
        self.rt.write_file(self.a, "src/app.py", "v1")
        cp = self.rt.checkpoint(self.a)
        self.rt.delete_file(self.a, "src/app.py")
        self.assertEqual(self.rt.diff(self.a), {"src/app.py": "<deleted>"})
        with self.assertRaises(ScopeError): self.rt.read_file(self.a, "src/app.py")
        self.rt.rollback(self.a, cp)
        self.assertEqual(self.rt.read_file(self.a, "src/app.py"), "v1")

    def test_file_listing_is_scoped_bounded_and_prefix_filtered(self):
        self.rt.write_file(self.a, "src/app.py", "x")
        self.rt.write_file(self.a, "src/lib/util.py", "x")
        self.rt.write_file(self.a, "README.md", "x")
        self.assertEqual(self.rt.list_files(self.a), ("README.md", "src/app.py", "src/lib/util.py"))
        self.assertEqual(self.rt.list_files(self.a, "src"), ("src/app.py", "src/lib/util.py"))
        self.assertEqual(self.rt.list_files(self.a, "src", 1), ("src/app.py",))
        for bad_limit in (0, -1, 1001, True, "10"):
            with self.assertRaises(ScopeError): self.rt.list_files(self.a, limit=bad_limit)
        for bad_prefix in ("../", "/abs", "a//b", "C:/secret", "a\\b"):
            with self.assertRaises(ScopeError): self.rt.list_files(self.a, bad_prefix)

    def test_resource_quotas_bound_laptop_memory_growth(self):
        # UTF-8 bytes, not Python character count: multibyte text cannot bypass quotas.
        with self.assertRaises(ScopeError):
            self.rt.write_file(self.a, "too-big.txt", "€" * (MAX_FILE_BYTES // 3 + 1))
        self.rt.write_file(self.a, "base.txt", "x" * MAX_FILE_BYTES)
        self.assertEqual(self.rt.inspect(self.a)["bytes_used"], MAX_FILE_BYTES)

        # Exercise aggregate-byte quota without allocating the full production limit.
        import builder_runtime_adapter_fake as mod
        old_total = mod.MAX_SESSION_BYTES
        try:
            mod.MAX_SESSION_BYTES = MAX_FILE_BYTES + 10
            with self.assertRaises(ScopeError):
                self.rt.write_file(self.a, "overflow.txt", "y" * 11)
        finally:
            mod.MAX_SESSION_BYTES = old_total

        # Exercise count quotas with temporary small limits to keep regressions fast/light.
        old_files, old_logs, old_cps = mod.MAX_SESSION_FILES, mod.MAX_LOG_EVENTS, mod.MAX_CHECKPOINTS
        try:
            mod.MAX_SESSION_FILES = len(self.rt.list_files(self.a))
            with self.assertRaises(ScopeError): self.rt.write_file(self.a, "extra.txt", "x")
            mod.MAX_LOG_EVENTS = 1
            self.rt.run(self.a, "one")
            with self.assertRaises(ScopeError): self.rt.run(self.a, "two")
            mod.MAX_CHECKPOINTS = 2  # includes checkpoint zero
            self.rt.checkpoint(self.a)
            with self.assertRaises(ScopeError): self.rt.checkpoint(self.a)
        finally:
            mod.MAX_SESSION_FILES, mod.MAX_LOG_EVENTS, mod.MAX_CHECKPOINTS = old_files, old_logs, old_cps

    def test_rollback_must_be_in_owned_history(self):
        self.assertEqual(self.rt.checkpoint(self.a), 1)
        with self.assertRaises(ScopeError): self.rt.rollback(self.a, 2)
        with self.assertRaises(ScopeError): self.rt.rollback(self.a, -1)
        with self.assertRaises(ScopeError): self.rt.rollback(self.a, True)
        self.assertEqual(self.rt.rollback(self.a, 0), 0)

    def test_paths_fail_closed(self):
        for path in ("../secret", "/abs", "a//b", "a/./b", "a/../b", "C:/secret", "a\\b", ""):
            with self.assertRaises(ScopeError): self.rt.write_file(self.a, path, "x")

    def test_stop_revokes_all_access_and_cannot_resurrect(self):
        self.rt.preview(self.a)
        self.rt.stop(self.a)
        self.assert_denied(self.a)
        with self.assertRaises(ScopeError): self.rt.create(self.a)

    def test_malformed_scope_fails_closed(self):
        for bad in (
            self.mutate(chat_id=""), self.mutate(project_id=" "),
            self.mutate(repo_scope=""), self.mutate(builder_session_id=""),
            self.mutate(state_epoch=-1), self.mutate(state_epoch=True),
        ):
            self.assert_denied(bad)


if __name__ == "__main__":
    unittest.main()
