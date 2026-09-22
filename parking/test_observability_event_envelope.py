import unittest
from parking.observability_event_envelope import create_event, public_dict, same_scope


BASE = dict(event_id="evt-1", kind="builder", level="info", chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/example")


class ObservabilityEnvelopeTests(unittest.TestCase):
    def test_valid_event_and_exact_scope(self):
        event = create_event(**BASE, fields={"status": "ok", "duration_ms": 42})
        self.assertTrue(same_scope(event, chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/example"))

    def test_cross_scope_denied(self):
        event = create_event(**BASE, fields={})
        self.assertFalse(same_scope(event, chat_id="chat-2", project_id="proj-1", repo_scope="C:/repos/example"))
        self.assertFalse(same_scope(event, chat_id="chat-1", project_id="proj-2", repo_scope="C:/repos/example"))
        self.assertFalse(same_scope(event, chat_id="chat-1", project_id="proj-1", repo_scope="C:/repos/other"))

    def test_sensitive_fields_rejected(self):
        for key in ("prompt", "token", "api_key", "authorization", "repo_scope", "path", "cwd", "url"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                create_event(**BASE, fields={key: "secret"})

    def test_unknown_fields_rejected(self):
        with self.assertRaises(ValueError):
            create_event(**BASE, fields={"random": "x"})

    def test_payload_bounds(self):
        with self.assertRaises(ValueError):
            create_event(**BASE, fields={"reason_code": "x" * 161})
        with self.assertRaises(ValueError):
            create_event(**BASE, fields={"duration_ms": 10_000_001})

    def test_path_like_ids_rejected(self):
        with self.assertRaises(ValueError):
            create_event(**{**BASE, "event_id": "../evt"}, fields={})

    def test_invalid_kind_or_level_rejected(self):
        with self.assertRaises(ValueError):
            create_event(**{**BASE, "kind": "shell"}, fields={})
        with self.assertRaises(ValueError):
            create_event(**{**BASE, "level": "fatal"}, fields={})

    def test_public_shape_contains_no_raw_scope(self):
        event = create_event(**BASE, fields={"provider_id": "local", "attempt": 1})
        data = public_dict(event)
        text = repr(data)
        self.assertNotIn("C:/repos/example", text)
        self.assertNotIn("chat-1", text)
        self.assertNotIn("proj-1", text)


if __name__ == "__main__":
    unittest.main()
