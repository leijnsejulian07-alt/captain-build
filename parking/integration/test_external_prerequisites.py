import unittest

from external_prerequisites import create_verified_prerequisite, validate_external_prerequisites

BASE = "a" * 40
MANIFEST = {"external_prerequisites": ["local-openbuilder-bridge", "research-project-state-bridge"]}
NOW = "2026-08-31T12:15:00Z"
FRESH = "2026-08-31T12:05:00Z"
EXPIRED = "2026-08-31T11:59:59Z"
FUTURE = "2026-08-31T12:16:01Z"


class ExternalPrerequisiteTests(unittest.TestCase):
    def test_valid_evidence_unlocks_only_named_prerequisite(self):
        row = create_verified_prerequisite("local-openbuilder-bridge", BASE, "doctor", verified_at=FRESH)
        self.assertEqual(
            validate_external_prerequisites(MANIFEST, {"local-openbuilder-bridge": row}, BASE, now=NOW),
            {"local-openbuilder-bridge"},
        )

    def test_stale_local_base_fails_closed(self):
        row = create_verified_prerequisite("local-openbuilder-bridge", BASE, "doctor", verified_at=FRESH)
        with self.assertRaisesRegex(ValueError, "stale"):
            validate_external_prerequisites(MANIFEST, {"local-openbuilder-bridge": row}, "b" * 40, now=NOW)

    def test_expired_evidence_fails_closed(self):
        row = create_verified_prerequisite("local-openbuilder-bridge", BASE, "doctor", verified_at=EXPIRED)
        with self.assertRaisesRegex(ValueError, "expired"):
            validate_external_prerequisites(MANIFEST, {"local-openbuilder-bridge": row}, BASE, now=NOW)

    def test_future_evidence_fails_closed(self):
        row = create_verified_prerequisite("local-openbuilder-bridge", BASE, "doctor", verified_at=FUTURE)
        with self.assertRaisesRegex(ValueError, "future"):
            validate_external_prerequisites(MANIFEST, {"local-openbuilder-bridge": row}, BASE, now=NOW)

    def test_tampered_timestamp_fails_closed(self):
        row = create_verified_prerequisite("local-openbuilder-bridge", BASE, "doctor", verified_at=FRESH)
        row["verified_at"] = "2026-08-31T12:06:00Z"
        with self.assertRaisesRegex(ValueError, "modified"):
            validate_external_prerequisites(MANIFEST, {"local-openbuilder-bridge": row}, BASE, now=NOW)

    def test_tampered_digest_fails_closed(self):
        row = create_verified_prerequisite("local-openbuilder-bridge", BASE, "doctor", verified_at=FRESH)
        row["evidence_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "modified"):
            validate_external_prerequisites(MANIFEST, {"local-openbuilder-bridge": row}, BASE, now=NOW)

    def test_substitution_fails_closed(self):
        row = create_verified_prerequisite("local-openbuilder-bridge", BASE, "doctor", verified_at=FRESH)
        with self.assertRaises(ValueError):
            validate_external_prerequisites(MANIFEST, {"research-project-state-bridge": row}, BASE, now=NOW)

    def test_unknown_prerequisite_fails_closed(self):
        row = create_verified_prerequisite("unknown-bridge", BASE, "doctor", verified_at=FRESH)
        with self.assertRaisesRegex(ValueError, "unknown"):
            validate_external_prerequisites(MANIFEST, {"unknown-bridge": row}, BASE, now=NOW)

    def test_extra_fields_fail_closed(self):
        row = create_verified_prerequisite("local-openbuilder-bridge", BASE, "doctor", verified_at=FRESH)
        row["note"] = "trusted"
        with self.assertRaisesRegex(ValueError, "malformed"):
            validate_external_prerequisites(MANIFEST, {"local-openbuilder-bridge": row}, BASE, now=NOW)

    def test_invalid_verifier_fails_closed(self):
        with self.assertRaises(ValueError):
            create_verified_prerequisite("local-openbuilder-bridge", BASE, "../doctor", verified_at=FRESH)


if __name__ == "__main__":
    unittest.main()
