import unittest

from connector_dispatch_ticket import ConnectorDispatchTicketError, consume_dispatch_ticket, issue_dispatch_ticket
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


def issue(envelope=None, **overrides):
    args = {
        "chat_id": "chat-a",
        "project_id": "project-a",
        "repo_scope": "owner/repo",
        "connector_id": "github",
        "action": "repo",
        "request_id": "req-1",
        "issued_at": "2026-09-02T08:17:00+00:00",
        "expires_at": "2026-09-02T08:17:20+00:00",
    }
    args.update(overrides)
    return issue_dispatch_ticket(envelope or bind(), **args)


def consume(ticket, envelope=None, ledger=None, **overrides):
    args = {
        "chat_id": "chat-a",
        "project_id": "project-a",
        "repo_scope": "owner/repo",
        "connector_id": "github",
        "action": "repo",
        "request_id": "req-1",
        "now": "2026-09-02T08:17:10+00:00",
        "consumed_ticket_ids": ledger if ledger is not None else set(),
    }
    args.update(overrides)
    return consume_dispatch_ticket(ticket, envelope or bind(), **args)


class ConnectorDispatchTicketTests(unittest.TestCase):
    def test_happy_path_and_single_use(self):
        envelope = bind()
        ticket = issue(envelope)
        ledger = set()
        result = consume(ticket, envelope, ledger)
        self.assertTrue(result["authorized"])
        with self.assertRaises(ConnectorDispatchTicketError):
            consume(ticket, envelope, ledger)

    def test_cross_project_replay_fails_closed(self):
        envelope = bind()
        ticket = issue(envelope)
        with self.assertRaises(ConnectorDispatchTicketError):
            consume(ticket, envelope, project_id="project-b")

    def test_request_replay_for_other_operation_fails_closed(self):
        envelope = bind()
        ticket = issue(envelope)
        with self.assertRaises(ConnectorDispatchTicketError):
            consume(ticket, envelope, request_id="req-2")

    def test_ticket_tamper_fails_closed(self):
        envelope = bind()
        ticket = issue(envelope)
        ticket["action"] = "read"
        with self.assertRaises(ConnectorDispatchTicketError):
            consume(ticket, envelope)

    def test_state_change_between_issue_and_dispatch_fails_closed(self):
        envelope = bind()
        ticket = issue(envelope)
        changed = ready_state()
        changed["permissions_granted"] = ["read"]
        changed["permissions_required"] = ["read"]
        changed_envelope = bind(changed)
        with self.assertRaises(ConnectorDispatchTicketError):
            consume(ticket, changed_envelope)

    def test_expired_ticket_fails_closed(self):
        envelope = bind()
        ticket = issue(envelope)
        with self.assertRaises(ConnectorDispatchTicketError):
            consume(ticket, envelope, now="2026-09-02T08:17:21+00:00")

    def test_future_ticket_beyond_skew_fails_closed(self):
        envelope = bind()
        ticket = issue(envelope)
        with self.assertRaises(ConnectorDispatchTicketError):
            consume(ticket, envelope, now="2026-09-02T08:16:54+00:00")

    def test_long_ttl_fails_closed(self):
        with self.assertRaises(ConnectorDispatchTicketError):
            issue(expires_at="2026-09-02T08:18:00+00:00")

    def test_unknown_fields_fail_closed(self):
        envelope = bind()
        ticket = issue(envelope)
        ticket["extra"] = True
        with self.assertRaises(ConnectorDispatchTicketError):
            consume(ticket, envelope)


if __name__ == "__main__":
    unittest.main()
