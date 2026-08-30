import unittest
from connector_notice_contract import (
    ConnectorNoticeError, dismiss, make_notice, public_payload
)

class ConnectorNoticeTests(unittest.TestCase):
    def test_unresolved_notice_visible(self):
        n = make_notice("github", "reconnect", 10)
        self.assertTrue(n.visible(10, False))

    def test_resolved_notice_clears(self):
        n = make_notice("github", "reconnect", 10)
        self.assertFalse(n.visible(10, True))

    def test_dismissal_reappears(self):
        n = dismiss(make_notice("github", "reconnect", 10), 20, 3600)
        self.assertFalse(n.visible(3619, False))
        self.assertTrue(n.visible(3620, False))

    def test_project_scopes_do_not_collide(self):
        a = make_notice("github", "reconnect", 1, "alpha")
        b = make_notice("github", "reconnect", 1, "beta")
        self.assertNotEqual(a.scope_hash, b.scope_hash)

    def test_nonimportant_notice_not_persistent(self):
        with self.assertRaises(ConnectorNoticeError):
            make_notice("github", "enable", 1)

    def test_bad_connector_id_rejected(self):
        with self.assertRaises(ConnectorNoticeError):
            make_notice("../github", "reconnect", 1)

    def test_dismissal_is_bounded(self):
        n = make_notice("github", "reconnect", 1)
        with self.assertRaises(ConnectorNoticeError):
            dismiss(n, 2, 99999999)

    def test_public_shape_has_no_secret_fields(self):
        payload = public_payload(make_notice("gmail", "update-setup", 1))
        self.assertFalse({"token", "secret", "api_key", "authorization"} & set(payload))

if __name__ == "__main__":
    unittest.main()
