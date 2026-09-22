from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
from pathlib import Path
import sqlite3


class RollbackLedgerError(ValueError):
    pass


SCHEMA_VERSION = 1
MAX_ID_LEN = 128
MAX_SCOPE_LEN = 300


def _text(value: object, name: str, max_len: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_len or value.strip() != value:
        raise RollbackLedgerError(f"invalid {name}")
    return value


def _hex64(value: object, name: str) -> str:
    value = _text(value, name, 64)
    if len(value) != 64:
        raise RollbackLedgerError(f"invalid {name}")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise RollbackLedgerError(f"invalid {name}") from exc
    return value.lower()


def _utc(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise RollbackLedgerError(f"invalid {name}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RollbackLedgerError(f"invalid {name}") from exc
    if parsed.tzinfo is None:
        raise RollbackLedgerError(f"naive {name}")
    return parsed.astimezone(timezone.utc).isoformat()


def _scope_digest(
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    state_epoch: int,
    builder_session_id: str,
) -> str:
    if not isinstance(state_epoch, int) or isinstance(state_epoch, bool) or state_epoch < 0:
        raise RollbackLedgerError("invalid state_epoch")
    payload = {
        "chat_id": _text(chat_id, "chat_id", MAX_ID_LEN),
        "project_id": _text(project_id, "project_id", MAX_ID_LEN),
        "repo_scope": _text(repo_scope, "repo_scope", MAX_SCOPE_LEN),
        "state_epoch": state_epoch,
        "builder_session_id": _text(builder_session_id, "builder_session_id", MAX_ID_LEN),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256(encoded).hexdigest()


def _request_digest(source_request_id: str) -> str:
    source_request_id = _text(source_request_id, "source_request_id", MAX_ID_LEN)
    return sha256(source_request_id.encode("utf-8")).hexdigest()


class SQLiteRollbackAuthorityLedger:
    """Durable fail-closed single-use ledger for builder rollback authority.

    Only digests/timestamps are stored. Raw chat/project/repo/session identifiers,
    checkpoint payloads, source request IDs and secrets are never persisted.
    Atomic INSERT under a UNIQUE primary key guarantees that concurrent or
    post-restart replay attempts have exactly one possible winner.
    """

    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        if not path.name:
            raise RollbackLedgerError("invalid db_path")
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
                CREATE TABLE IF NOT EXISTS consumed_builder_rollbacks (
                    checkpoint_binding TEXT PRIMARY KEY NOT NULL,
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
        checkpoint_binding: str,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        state_epoch: int,
        builder_session_id: str,
        source_request_id: str,
        consumed_at: str,
    ) -> bool:
        checkpoint_binding = _hex64(checkpoint_binding, "checkpoint_binding")
        scope_digest = _scope_digest(
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            state_epoch=state_epoch,
            builder_session_id=builder_session_id,
        )
        request_digest = _request_digest(source_request_id)
        consumed = _utc(consumed_at, "consumed_at")

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT INTO consumed_builder_rollbacks
                    (checkpoint_binding, schema_version, scope_digest, request_digest, consumed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (checkpoint_binding, SCHEMA_VERSION, scope_digest, request_digest, consumed),
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
        checkpoint_binding: str,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        state_epoch: int,
        builder_session_id: str,
        source_request_id: str,
    ) -> bool:
        checkpoint_binding = _hex64(checkpoint_binding, "checkpoint_binding")
        expected_scope = _scope_digest(
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            state_epoch=state_epoch,
            builder_session_id=builder_session_id,
        )
        expected_request = _request_digest(source_request_id)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT schema_version, scope_digest, request_digest
                FROM consumed_builder_rollbacks
                WHERE checkpoint_binding = ?
                """,
                (checkpoint_binding,),
            ).fetchone()
        if row is None:
            return False
        schema_version, scope_digest, request_digest = row
        if schema_version != SCHEMA_VERSION:
            raise RollbackLedgerError("unsupported stored schema")
        return hmac.compare_digest(scope_digest, expected_scope) and hmac.compare_digest(
            request_digest, expected_request
        )
