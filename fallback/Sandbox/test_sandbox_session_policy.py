import unittest

from sandbox_session_policy import (
    assert_sandbox_access,
    create_sandbox_lease,
    validate_launch_capabilities,
)


class SandboxSessionPolicyTests(unittest.TestCase):
    def make(self, **overrides):
        args = dict(
            session_id="s1",
            chat_id="c1",
            project_id="p1",
            repo_scope=r"C:\repos\alpha",
            state_epoch=7,
        )
        args.update(overrides)
        return create_sandbox_lease(**args)

    def test_safe_defaults(self):
        lease = self.make()
        self.assertEqual(lease.backend, "docker-sbx")
        self.assertEqual(lease.workspace_mode, "clone")
        self.assertEqual(lease.network_mode, "deny")
        self.assertEqual(lease.credential_mode, "proxy")

    def test_exact_scope_allowed(self):
        assert_sandbox_access(
            self.make(), chat_id="c1", project_id="p1",
            repo_scope=r"C:\repos\alpha", state_epoch=7,
        )

    def test_cross_project_denied(self):
        with self.assertRaises(PermissionError):
            assert_sandbox_access(
                self.make(), chat_id="c1", project_id="p2",
                repo_scope=r"C:\repos\alpha", state_epoch=7,
            )

    def test_cross_chat_denied(self):
        with self.assertRaises(PermissionError):
            assert_sandbox_access(
                self.make(), chat_id="c2", project_id="p1",
                repo_scope=r"C:\repos\alpha", state_epoch=7,
            )

    def test_cross_repo_denied(self):
        with self.assertRaises(PermissionError):
            assert_sandbox_access(
                self.make(), chat_id="c1", project_id="p1",
                repo_scope=r"C:\repos\beta", state_epoch=7,
            )

    def test_stale_epoch_denied(self):
        with self.assertRaises(PermissionError):
            assert_sandbox_access(
                self.make(), chat_id="c1", project_id="p1",
                repo_scope=r"C:\repos\alpha", state_epoch=8,
            )

    def test_unsafe_workspace_mode_rejected(self):
        with self.assertRaises(ValueError):
            self.make(workspace_mode="host-rw")

    def test_unknown_backend_rejected(self):
        with self.assertRaises(ValueError):
            self.make(backend="random-daemon")

    def test_network_is_deny_by_default(self):
        with self.assertRaises(PermissionError):
            validate_launch_capabilities(self.make(), requested_network_hosts=("github.com",))

    def test_allowlist_rejects_url_shaped_entry(self):
        lease = self.make(network_mode="allowlist")
        with self.assertRaises(ValueError):
            validate_launch_capabilities(lease, requested_network_hosts=("https://github.com",))

    def test_allowlist_accepts_hostnames_only(self):
        lease = self.make(network_mode="allowlist")
        validate_launch_capabilities(lease, requested_network_hosts=("github.com", "api.github.com"))

    def test_raw_secrets_denied(self):
        with self.assertRaises(PermissionError):
            validate_launch_capabilities(self.make(), raw_secret_values_present=True)

    def test_invalid_epoch_rejected(self):
        with self.assertRaises(ValueError):
            self.make(state_epoch=0)


if __name__ == "__main__":
    unittest.main()
