import unittest

from parking.connector_action_authorizer import MAX_ACTION, authorize


def state(**changes):
    base = {
        "installed": True,
        "connected": True,
        "enabled": True,
        "ready": True,
        "permissions": ["repo.read", "repo.write"],
    }
    base.update(changes)
    return base


class ConnectorActionAuthorizerTests(unittest.TestCase):
    def test_exact_permission_is_authorized(self):
        self.assertEqual(
            authorize(state(), "repo.write"),
            {"allowed": True, "reason": "authorized"},
        )

    def test_permission_is_exact_match_only(self):
        for action in ("repo", "repo.write.force", "repo.read.extra"):
            with self.subTest(action=action):
                self.assertEqual(authorize(state(), action)["reason"], "permission_denied")

    def test_each_readiness_dimension_fails_closed(self):
        for key in ("installed", "connected", "enabled", "ready"):
            for value in (False, None, 0, 1, "true"):
                with self.subTest(key=key, value=value):
                    decision = authorize(state(**{key: value}), "repo.read")
                    self.assertFalse(decision["allowed"])
                    self.assertEqual(decision["reason"], "connector_not_ready")

    def test_missing_readiness_dimension_fails_closed(self):
        for key in ("installed", "connected", "enabled", "ready"):
            candidate = state()
            del candidate[key]
            with self.subTest(key=key):
                self.assertEqual(
                    authorize(candidate, "repo.read")["reason"],
                    "connector_not_ready",
                )

    def test_malformed_state_fails_closed(self):
        for candidate in (None, [], (), "state", True, 1):
            with self.subTest(candidate=repr(candidate)):
                self.assertEqual(
                    authorize(candidate, "repo.read"),
                    {"allowed": False, "reason": "invalid_state"},
                )

    def test_malformed_actions_fail_closed(self):
        bad = (
            None, True, 1, "", " repo.read", "repo.read ", "Repo.read",
            "repo/read", "repo.*", "*", "a" * (MAX_ACTION + 1),
        )
        for action in bad:
            with self.subTest(action=repr(action)):
                self.assertEqual(authorize(state(), action)["reason"], "invalid_action")

    def test_malformed_permissions_fail_closed(self):
        bad = (
            None,
            "repo.read",
            {"repo.read"},
            {"repo.read": True},
            [True],
            [1],
            [""],
            ["Repo.read"],
            ["repo/read"],
            ["repo.*"],
            ["repo.read", "repo.read"],
            ["a" * (MAX_ACTION + 1)],
            ["p%d" % i for i in range(129)],
        )
        for permissions in bad:
            with self.subTest(permissions=repr(permissions)[:100]):
                decision = authorize(state(permissions=permissions), "repo.read")
                self.assertFalse(decision["allowed"])
                self.assertEqual(decision["reason"], "invalid_permissions")

    def test_missing_permission_is_denied_without_echoing_input(self):
        decision = authorize(state(permissions=["repo.read"]), "repo.write")
        self.assertEqual(decision, {"allowed": False, "reason": "permission_denied"})
        self.assertNotIn("repo.write", repr(decision))

    def test_tuple_permissions_are_supported_but_not_implicit_authority(self):
        self.assertTrue(
            authorize(state(permissions=("repo.read",)), "repo.read")["allowed"]
        )
        self.assertFalse(
            authorize(state(permissions=("repo",)), "repo.read")["allowed"]
        )


if __name__ == "__main__":
    unittest.main()
