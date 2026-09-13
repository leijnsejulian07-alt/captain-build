from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
from pathlib import Path
import sqlite3


class DispatchLedgerError(ValueError):
    pass


SCHEMA_VERSION = 1
MAX_ID_LEN = 128
MAX_SCOPE_LEN = 300


def _text(value: object, name: str, max_len: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_len or value.strip() != value:
        raise DispatchLedgerError(f"invalid {name}")
    return value


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise DispatchLedgerError(f"invalid {name}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DispatchLedgerError(f"invalid {name}") from exc
    if parsed.tzinfo is None:
        raise DispatchLedgerError(f"naive {name}")
    return parsed.astimezone(timezone.utc)


def _scope_digest(*, chat_id: str, project_id: str, repo_scope: str) -> str:
    payload = {
        "chat_id": _text(chat_id, "chat_id", MAX_ID_LEN),
        "project_id": _text(project_id, "project_id", MAX_ID_LEN),
        "repo_scope": _text(repo_scope, "repo_scope", MAX_SCOPE_LEN),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256(encoded).hexdigest()


def _request_digest(request_id: str) -> str:
    request_id = _text(request_id, "request_id", MAX_ID_LEN)
    return sha256(request_id.encode("utf-8")).hexdigest()


def _validate_ticket_id(ticket_id: object) -> str:
    ticket_id = _text(ticket_id, "ticket_id", 64)
    if len(ticket_id) != 64:
        raise DispatchLedgerError("invalid ticket_id")
    try:
        bytes.fromhex(ticket_id)
    except ValueError as exc:
        raise DispatchLedgerError("invalid ticket_id") from exc
    return ticket_id.lower()


class SQLiteDispatchLedger:
    """Durable single-use dispatch-ticket ledger.

    Stores only ticket/request/scope digests plus timestamps. It never stores connector
    credentials, provider payloads, raw chat/project IDs, or raw repo scopes. Each
    consume is an atomic INSERT guarded by a UNIQUE primary key, so concurrent attempts
    for the same ticket have exactly one winner.
    """

    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        if not path.name:
            raise DispatchLedgerError("invalid db_path")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consumed_dispatch_tickets (
                    ticket_id TEXT PRIMARY KEY NOT NULL,
                    schema_version INTEGER NOT NULL,
                    scope_digest TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    consumed_at TEXT NOT NULL
                )
                """
            )

    def consume_once(
        self,
        *,
        ticket_id: str,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        request_id: str,
        consumed_at: str,
    ) -> bool:
        ticket_id = _validate_ticket_id(ticket_id)
        scope_digest = _scope_digest(chat_id=chat_id, project_id=project_id, repo_scope=repo_scope)
        request_digest = _request_digest(request_id)
        consumed = _utc(consumed_at, "consumed_at").isoformat()

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT INTO consumed_dispatch_tickets
                    (ticket_id, schema_version, scope_digest, request_digest, consumed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (ticket_id, SCHEMA_VERSION, scope_digest, request_digest, consumed),
                )
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK")
                return False
            conn.execute("COMMIT")
            return True
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def verify_consumed(
        self,
        *,
        ticket_id: str,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        request_id: str,
    ) -> bool:
        ticket_id = _validate_ticket_id(ticket_id)
        expected_scope = _scope_digest(chat_id=chat_id, project_id=project_id, repo_scope=repo_scope)
        expected_request = _request_digest(request_id)

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT schema_version, scope_digest, request_digest
                FROM consumed_dispatch_tickets
                WHERE ticket_id = ?
                """,
                (ticket_id,),
            ).fetchone()
        if row is None:
            return False
        schema_version, scope_digest, request_digest = row
        if schema_version != SCHEMA_VERSION:
            raise DispatchLedgerError("unsupported stored schema")
        return hmac.compare_digest(scope_digest, expected_scope) and hmac.compare_digest(
            request_digest, expected_request
        )
