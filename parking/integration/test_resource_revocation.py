import copy
import unittest

from parking.integration.resource_revocation import (
    assert_not_revoked,
    create_revocation,
    validate_revocation,
)


class ResourceRevocationTests(unittest.TestCase):
    def setUp(self):
        self.binding_digest = "a" * 64
        self.principal = "plugin-alpha"
        self.kind = "preview_session"
        self.resource_id = "preview-1"
        self.generation = 4

    def _create(self, **overrides):
        args = {
            "binding_digest": self.binding_digest,
            "principal_id": self.principal,
            "resource_kind": self.kind,
            "resource_id": self.resource_id,
            "resource_generation": self.generation,
            "revoked_at": 1_788_214_800,
            "reason": "resource_stopped",
        }
        args.update(overrides)
        return create_revocation(**args)

    def _validate(self, revocation, **overrides):
        args = {
            "expected_binding_digest": self.binding_digest,
            "expected_principal_id": self.principal,
            "expected_resource_kind": self.kind,
            "expected_resource_id": self.resource_id,
            "expected_resource_generation": self.generation,
        }
        args.update(overrides)
        return validate_revocation(revocation, **args)

    def test_round_trip(self):
        revocation = self._create()
        self.assertEqual(self._validate(revocation), revocation)

    def test_revoked_resource_fails_closed(self):
        revocation = self._create()
        with self.assertRaises(PermissionError):
            assert_not_revoked(
                revocation,
                expected_binding_digest=self.binding_digest,
                expected_principal_id=self.principal,
                expected_resource_kind=self.kind,
                expected_resource_id=self.resource_id,
                expected_resource_generation=self.generation,
            )

    def test_absent_revocation_is_allowed(self):
        self.assertIsNone(
            assert_not_revoked(
                None,
                expected_binding_digest=self.binding_digest,
                expected_principal_id=self.principal,
                expected_resource_kind=self.kind,
                expected_resource_id=self.resource_id,
                expected_resource_generation=self.generation,
            )
        )

    def test_cross_principal_revocation_cannot_revoke_other_owner(self):
        revocation = self._create(principal_id="plugin-beta")
        with self.assertRaises(PermissionError):
            self._validate(revocation)

    def test_old_generation_revocation_cannot_revoke_reissued_resource(self):
        revocation = self._create(resource_generation=self.generation - 1)
        with self.assertRaises(PermissionError):
            self._validate(revocation)

    def test_other_binding_digest_cannot_revoke_resource(self):
        revocation = self._create(binding_digest="b" * 64)
        with self.assertRaises(PermissionError):
            self._validate(revocation)

    def test_tampering_breaks_digest(self):
        revocation = self._create()
        tampered = copy.deepcopy(revocation)
        tampered["reason"] = "security_reset"
        with self.assertRaises(ValueError):
            self._validate(tampered)

    def test_unknown_fields_fail_closed(self):
        revocation = self._create()
        revocation["extra"] = "ignored-by-old-code"
        with self.assertRaises(ValueError):
            self._validate(revocation)

    def test_invalid_reasons_and_identifiers_fail_closed(self):
        for kwargs in (
            {"reason": "other"},
            {"principal_id": "../plugin"},
            {"resource_kind": "Preview"},
            {"resource_id": "../preview"},
            {"resource_generation": 0},
            {"resource_generation": True},
            {"revoked_at": 0},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self._create(**kwargs)


if __name__ == "__main__":
    unittest.main()
