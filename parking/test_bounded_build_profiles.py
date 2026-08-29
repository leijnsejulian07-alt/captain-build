import unittest

from bounded_build_profiles import ProfileError, compile_profile, materialize_for_execution


class BoundedBuildProfileTests(unittest.TestCase):
    def base(self, **overrides):
        data = dict(
            profile_id="python-tests",
            kind="test",
            executable="python",
            args=("-m", "unittest"),
            cwd="C:/repo/app",
            repo_scope="C:/repo",
            timeout_seconds=120,
            allowed_executables={"python", "npm", "node"},
        )
        data.update(overrides)
        return compile_profile(**data)

    def test_valid_profile_materializes_without_shell(self):
        p = self.base()
        argv, cwd, timeout = materialize_for_execution(p, cwd="C:/repo/app", repo_scope="C:/repo")
        self.assertEqual(argv, ["python", "-m", "unittest"])
        self.assertTrue(cwd.replace("\\", "/").endswith("/repo/app"))
        self.assertEqual(timeout, 120)

    def test_rejects_unlisted_executable(self):
        with self.assertRaises(ProfileError):
            self.base(executable="powershell")

    def test_rejects_path_to_executable_even_if_named_allowlisted(self):
        with self.assertRaises(ProfileError):
            self.base(executable="C:/Python/python")

    def test_rejects_cwd_escape(self):
        with self.assertRaises(ProfileError):
            self.base(cwd="C:/other")

    def test_rejects_unknown_kind(self):
        with self.assertRaises(ProfileError):
            self.base(kind="shell")

    def test_rejects_bad_profile_id(self):
        with self.assertRaises(ProfileError):
            self.base(profile_id="../escape")

    def test_rejects_control_characters_in_args(self):
        with self.assertRaises(ProfileError):
            self.base(args=("ok", "bad\nnext"))

    def test_rejects_unbounded_timeout(self):
        with self.assertRaises(ProfileError):
            self.base(timeout_seconds=3600)

    def test_materialization_rechecks_cwd(self):
        p = self.base()
        with self.assertRaises(ProfileError):
            materialize_for_execution(p, cwd="C:/repo/other", repo_scope="C:/repo")

    def test_profile_does_not_expose_local_path(self):
        p = self.base()
        self.assertFalse(hasattr(p, "cwd"))
        self.assertEqual(len(p.cwd_hash), 64)


if __name__ == "__main__":
    unittest.main()
