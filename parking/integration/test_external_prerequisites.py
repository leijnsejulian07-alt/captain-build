import unittest

from external_prerequisites import create_verified_prerequisite, validate_external_prerequisites

BASE = "a" * 40
MANIFEST = {"external_prerequisites": ["local-openbuilder-bridge", "research-project-state-bridge"]}


class ExternalPrerequisiteTests(unittest.TestCase):
    def test_valid_evidence_unlocks_only_named_prerequisite(self):
        row = create_verified_prerequisite("local-openbuilder-bridge", BASE, "doctor")
        self.assertEqual(
            validate_external_prerequisites(MANIFEST, {"local-openbuilder-bridge": row}, BASE),
            {"local-openbuilder-bridge"},
        )

    def test_stale_local_base_fails_closed(self):
        row = create_verified_prerequisite("local-openbuilder-bridge", BASE, "doctor")
        with self.assertRaisesRegex(ValueError, "stale"):
            validate_external_prerequisites(MANIFEST, {"local-openbuilder-bridge": row}, "b" * 40)

    def test_tampered_digest_fails_closed(self):
        row = create_verified_prerequisite("local-openbuilder-bridge", BASE, "doctor")
        row["evidence_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "modified"):
            validate_external_prerequisites(MANIFEST, {"local-openbuilder-bridge": row}, BASE)

    def test_substitution_fails_closed(self):
        row = create_verified_prerequisite("local-openbuilder-bridge", BASE, "doctor")
        with self.assertRaises(ValueError):
            validate_external_prerequisites(MANIFEST, {"research-project-state-bridge": row}, BASE)

    def test_unknown_prerequisite_fails_closed(self):
        row = create_verified_prerequisite("unknown-bridge", BASE, "doctor")
        with self.assertRaisesRegex(ValueError, "unknown"):
            validate_external_prerequisites(MANIFEST, {"unknown-bridge": row}, BASE)

    def test_extra_fields_fail_closed(self):
        row = create_verified_prerequisite("local-openbuilder-bridge", BASE, "doctor")
        row["note"] = "trusted"
        with self.assertRaisesRegex(ValueError, "malformed"):
            validate_external_prerequisites(MANIFEST, {"local-openbuilder-bridge": row}, BASE)

    def test_invalid_verifier_fails_closed(self):
        with self.assertRaises(ValueError):
            create_verified_prerequisite("local-openbuilder-bridge", BASE, "../doctor")


if __name__ == "__main__":
    unittest.main()
