from __future__ import annotations

from connector_dispatch_ledger import DispatchLedgerError, SQLiteDispatchLedger
from connector_dispatch_ticket import ConnectorDispatchTicketError, consume_dispatch_ticket


class ConnectorDispatchRuntimeError(ValueError):
    pass


def consume_dispatch_ticket_durable(
    ticket: dict,
    envelope: dict,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    connector_id: str,
    action: str,
    request_id: str,
    now: str,
    ledger: SQLiteDispatchLedger,
) -> dict:
    """Fail closed unless a ticket is both currently valid and durably consumed once.

    Validation/re-authorization happens before the durable insert. The SQLite ledger then
    arbitrates concurrent/process-restart replay attempts atomically. No provider call is
    performed here; callers may dispatch only after this function returns authorized=True.
    """
    if not isinstance(ledger, SQLiteDispatchLedger):
        raise ConnectorDispatchRuntimeError("invalid durable ledger")

    try:
        decision = consume_dispatch_ticket(
            ticket,
            envelope,
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            connector_id=connector_id,
            action=action,
            request_id=request_id,
            now=now,
            consumed_ticket_ids=set(),
        )
    except ConnectorDispatchTicketError as exc:
        raise ConnectorDispatchRuntimeError("dispatch ticket validation failed") from exc

    try:
        won = ledger.consume_once(
            ticket_id=decision["ticket_id"],
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            request_id=request_id,
            consumed_at=now,
        )
    except DispatchLedgerError as exc:
        raise ConnectorDispatchRuntimeError("durable ledger rejected dispatch") from exc
    except Exception as exc:
        raise ConnectorDispatchRuntimeError("durable ledger unavailable") from exc

    if not won:
        raise ConnectorDispatchRuntimeError("dispatch ticket already consumed")

    return decision
