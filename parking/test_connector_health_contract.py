import unittest
from connector_health_contract import ConnectorState, ConnectorStateError, remediation_code, validate_state

KNOWN = {"repo:read", "repo:write", "mail:read"}

def state(**updates):
    data = dict(connector_id="github", installed=True, connected=True, enabled=True,
                auth_method="oauth", health="healthy", permissions=frozenset({"repo:read"}),
                setup_version=2, verified_setup_version=2)
    data.update(updates)
    return ConnectorState(**data)

class ConnectorHealthContractTests(unittest.TestCase):
    def test_ready_requires_all_independent_gates(self):
        self.assertTrue(validate_state(state(), KNOWN).ready)
        for field, value in (("installed", False), ("connected", False), ("enabled", False),
                             ("health", "degraded"), ("verified_setup_version", 1)):
            candidate = state(**{field: value})
            if field == "installed":
                candidate = state(installed=False, connected=False, enabled=False)
            self.assertFalse(validate_state(candidate, KNOWN).ready)

    def test_unknown_permission_fails_closed(self):
        with self.assertRaises(ConnectorStateError):
            validate_state(state(permissions=frozenset({"admin:anything"})), KNOWN)

    def test_connected_or_enabled_before_install_is_invalid(self):
        with self.assertRaises(ConnectorStateError): validate_state(state(installed=False), KNOWN)

    def test_expired_auth_demands_reconnect(self):
        self.assertEqual(remediation_code(state(health="expired")), "reconnect")

    def test_setup_migration_demands_update(self):
        self.assertEqual(remediation_code(state(setup_version=3)), "update-setup")

    def test_unconnected_oauth_demands_connect(self):
        self.assertEqual(remediation_code(state(connected=False)), "connect")

    def test_disabled_connector_is_not_ready_and_can_be_enabled(self):
        s = state(enabled=False)
        self.assertFalse(s.ready)
        self.assertEqual(remediation_code(s), "enable")

    def test_state_has_no_secret_field(self):
        names = ConnectorState.__dataclass_fields__
        self.assertFalse(any("secret" in x or "token" in x or "key" in x for x in names))

if __name__ == "__main__": unittest.main()
