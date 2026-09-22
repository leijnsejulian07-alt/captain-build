import unittest
from build_profile_detection import detect_build_profiles

class DetectionTests(unittest.TestCase):
    def test_node_lockfile(self):
        got = detect_build_profiles(["package.json", "package-lock.json"])
        self.assertEqual(got[0].ecosystem, "node")
        self.assertEqual(got[0].confidence, "high")

    def test_does_not_parse_scripts(self):
        got = detect_build_profiles(["package.json"], {"scripts": {"test": "rm -rf /"}})
        self.assertEqual(got[0].profile_ids, ("node:typecheck", "node:test", "node:build"))

    def test_python(self):
        got = detect_build_profiles(["pyproject.toml", "pytest.ini"])
        self.assertEqual(got[0].profile_ids, ("python:pytest",))
        self.assertEqual(got[0].confidence, "high")

    def test_polyglot_is_explicit(self):
        got = detect_build_profiles(["package.json", "go.mod", "Cargo.toml"])
        self.assertEqual([x.ecosystem for x in got], ["go", "node", "rust"])

    def test_unknown_files_do_nothing(self):
        self.assertEqual(detect_build_profiles(["README.md", "src/app.ts"]), ())

    def test_parent_escape_rejected(self):
        with self.assertRaises(ValueError): detect_build_profiles(["../package.json"])

    def test_absolute_rejected(self):
        with self.assertRaises(ValueError): detect_build_profiles(["/tmp/package.json"])

    def test_path_count_bounded(self):
        with self.assertRaises(ValueError): detect_build_profiles([f"src/{i}.txt" for i in range(4097)])

    def test_metadata_must_be_mapping(self):
        with self.assertRaises(ValueError): detect_build_profiles(["package.json"], "bad")

if __name__ == "__main__":
    unittest.main()
