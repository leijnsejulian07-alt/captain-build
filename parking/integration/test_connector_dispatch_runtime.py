import tempfile
import threading
import unittest
from pathlib import Path

from connector_dispatch_ledger import SQLiteDispatchLedger
from connector_dispatch_runtime import ConnectorDispatchRuntimeError, consume_dispatch_ticket_durable
from connector_dispatch_ticket import issue_dispatch_ticket
from connector_state_scope import bind_connector_state


def ready_state():
    return {
        "schema_version": 1,
        "connector_id": "github",
        "project_id": "project-a",
        "installed": True,
        "connected": True,
        "enabled": True,
        "ready": True,
        "auth_method": "oauth",
        "health": "healthy",
        "permissions_granted": ["read", "repo"],
        "permissions_required": ["read", "repo"],
        "issue_code": None,
    }


def bind(state=None):
    return bind_connector_state(
        state or ready_state(),
        chat_id="chat-a",
        project_id="project-a",
        repo_scope="owner/repo",
    )


def issue(envelope):
    return issue_dispatch_ticket(
        envelope,
        chat_id="chat-a",
        project_id="project-a",
        repo_scope="owner/repo",
        connector_id="github",
        action="repo",
        request_id="req-1",
        issued_at="2026-09-02T10:15:00+00:00",
        expires_at="2026-09-02T10:15:20+00:00",
    )


def consume(ticket, envelope, ledger, **overrides):
    args = {
        "chat_id": "chat-a",
        "project_id": "project-a",
        "repo_scope": "owner/repo",
        "connector_id": "github",
        "action": "repo",
        "request_id": "req-1",
        "now": "2026-09-02T10:15:10+00:00",
        "ledger": ledger,
    }
    args.update(overrides)
    return consume_dispatch_ticket_durable(ticket, envelope, **args)


class ConnectorDispatchRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "dispatch.sqlite3"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_happy_path_is_durable_across_reopen(self):
        envelope = bind()
        ticket = issue(envelope)
        result = consume(ticket, envelope, SQLiteDispatchLedger(self.db_path))
        self.assertTrue(result["authorized"])
        with self.assertRaises(ConnectorDispatchRuntimeError):
            consume(ticket, envelope, SQLiteDispatchLedger(self.db_path))

    def test_concurrent_consumers_have_exactly_one_winner(self):
        envelope = bind()
        ticket = issue(envelope)
        barrier = threading.Barrier(8)
        outcomes = []
        lock = threading.Lock()

        def worker():
            ledger = SQLiteDispatchLedger(self.db_path)
            barrier.wait()
            try:
                consume(ticket, envelope, ledger)
                value = "won"
            except ConnectorDispatchRuntimeError:
                value = "denied"
            with lock:
                outcomes.append(value)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes.count("won"), 1)
        self.assertEqual(outcomes.count("denied"), 7)

    def test_scope_mismatch_does_not_burn_ticket(self):
        envelope = bind()
        ticket = issue(envelope)
        ledger = SQLiteDispatchLedger(self.db_path)
        with self.assertRaises(ConnectorDispatchRuntimeError):
            consume(ticket, envelope, ledger, project_id="project-b")
        result = consume(ticket, envelope, ledger)
        self.assertTrue(result["authorized"])

    def test_state_change_does_not_burn_ticket(self):
        envelope = bind()
        ticket = issue(envelope)
        changed = ready_state()
        changed["enabled"] = False
        changed["ready"] = False
        changed_envelope = bind(changed)
        ledger = SQLiteDispatchLedger(self.db_path)
        with self.assertRaises(ConnectorDispatchRuntimeError):
            consume(ticket, changed_envelope, ledger)
        result = consume(ticket, envelope, ledger)
        self.assertTrue(result["authorized"])

    def test_non_durable_ledger_fails_closed(self):
        envelope = bind()
        ticket = issue(envelope)
        with self.assertRaises(ConnectorDispatchRuntimeError):
            consume(ticket, envelope, set())


if __name__ == "__main__":
    unittest.main()
