import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from connector_dispatch_ledger import DispatchLedgerError, SQLiteDispatchLedger


TICKET = "a" * 64


class DispatchLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "dispatch.sqlite3"
        self.ledger = SQLiteDispatchLedger(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def consume(self, **overrides):
        args = {
            "ticket_id": TICKET,
            "chat_id": "chat-a",
            "project_id": "project-a",
            "repo_scope": "owner/repo",
            "request_id": "req-1",
            "consumed_at": "2026-09-02T09:16:00+00:00",
        }
        args.update(overrides)
        return self.ledger.consume_once(**args)

    def test_first_consume_wins_and_second_fails(self):
        self.assertTrue(self.consume())
        self.assertFalse(self.consume())

    def test_persists_across_ledger_instances(self):
        self.assertTrue(self.consume())
        reopened = SQLiteDispatchLedger(self.path)
        self.assertFalse(reopened.consume_once(
            ticket_id=TICKET, chat_id="chat-a", project_id="project-a",
            repo_scope="owner/repo", request_id="req-1",
            consumed_at="2026-09-02T09:16:01+00:00"
        ))

    def test_scope_is_hashed_and_verified_fail_closed(self):
        self.assertTrue(self.consume())
        self.assertTrue(self.ledger.verify_consumed(
            ticket_id=TICKET, chat_id="chat-a", project_id="project-a",
            repo_scope="owner/repo", request_id="req-1"
        ))
        self.assertFalse(self.ledger.verify_consumed(
            ticket_id=TICKET, chat_id="chat-b", project_id="project-a",
            repo_scope="owner/repo", request_id="req-1"
        ))
        raw = self.path.read_bytes()
        self.assertNotIn(b"chat-a", raw)
        self.assertNotIn(b"project-a", raw)
        self.assertNotIn(b"owner/repo", raw)
        self.assertNotIn(b"req-1", raw)

    def test_request_mismatch_fails_verification(self):
        self.assertTrue(self.consume())
        self.assertFalse(self.ledger.verify_consumed(
            ticket_id=TICKET, chat_id="chat-a", project_id="project-a",
            repo_scope="owner/repo", request_id="req-2"
        ))

    def test_concurrent_consumption_has_exactly_one_winner(self):
        barrier = threading.Barrier(8)
        results = []
        errors = []
        lock = threading.Lock()

        def worker():
            try:
                barrier.wait()
                value = SQLiteDispatchLedger(self.path).consume_once(
                    ticket_id=TICKET, chat_id="chat-a", project_id="project-a",
                    repo_scope="owner/repo", request_id="req-1",
                    consumed_at="2026-09-02T09:16:00+00:00"
                )
                with lock:
                    results.append(value)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 7)

    def test_invalid_ticket_id_fails_closed(self):
        with self.assertRaises(DispatchLedgerError):
            self.consume(ticket_id="not-a-digest")

    def test_naive_timestamp_fails_closed_without_consuming(self):
        with self.assertRaises(DispatchLedgerError):
            self.consume(consumed_at="2026-09-02T09:16:00")
        self.assertTrue(self.consume())

    def test_unknown_stored_schema_fails_closed(self):
        self.assertTrue(self.consume())
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE consumed_dispatch_tickets SET schema_version = 99")
        with self.assertRaises(DispatchLedgerError):
            self.ledger.verify_consumed(
                ticket_id=TICKET, chat_id="chat-a", project_id="project-a",
                repo_scope="owner/repo", request_id="req-1"
            )


if __name__ == "__main__":
    unittest.main()
