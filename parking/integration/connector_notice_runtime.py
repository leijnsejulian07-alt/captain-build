from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
import sqlite3

from connector_settings_contract import ContractError, build_notice, should_surface, validate_connector_state

DEFAULT_REMINDER = timedelta(hours=24)
MAX_DISMISS = timedelta(days=7)


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ContractError(field)
    return value


def _digest(*parts: str) -> str:
    raw = json.dumps(parts, separators=(",", ":"), ensure_ascii=True)
    return sha256(raw.encode("utf-8")).hexdigest()


class ConnectorNoticeStore:
    """Durable, secret-free connector notice state for Captain Settings/app launch.

    Rows are keyed by digests of connector/project identity so persistent storage does not reveal
    raw project or connector identifiers. Notice payloads come from the existing canonical
    build_notice() contract and therefore contain no secrets.
    """

    def __init__(self, path: str) -> None:
        if not isinstance(path, str) or not path:
            raise ContractError("notice db path")
        self.path = path
        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS connector_notices (
                    scope_digest TEXT PRIMARY KEY,
                    issue_digest TEXT NOT NULL,
                    dismiss_until TEXT,
                    last_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.commit()

    @staticmethod
    def _scope_digest(state: dict) -> str:
        validate_connector_state(state)
        return _digest(state["connector_id"], state["project_id"])

    @staticmethod
    def _issue_digest(state: dict) -> str:
        validate_connector_state(state)
        issue = state["issue_code"] or "not_ready"
        return _digest(state["connector_id"], state["project_id"], issue)

    def clear_if_resolved(self, state: dict) -> bool:
        validate_connector_state(state)
        if not state["ready"]:
            return False
        scope = self._scope_digest(state)
        with sqlite3.connect(self.path) as db:
            cursor = db.execute("DELETE FROM connector_notices WHERE scope_digest = ?", (scope,))
            db.commit()
            return cursor.rowcount > 0

    def dismiss(self, state: dict, now: datetime, *, duration: timedelta = DEFAULT_REMINDER) -> datetime:
        validate_connector_state(state)
        now = _aware(now, "now")
        if state["ready"]:
            raise ContractError("cannot dismiss resolved connector")
        if not isinstance(duration, timedelta) or duration <= timedelta(0) or duration > MAX_DISMISS:
            raise ContractError("dismiss duration")
        until = now + duration
        scope = self._scope_digest(state)
        issue = self._issue_digest(state)
        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                INSERT INTO connector_notices(scope_digest, issue_digest, dismiss_until, last_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scope_digest) DO UPDATE SET
                    issue_digest = excluded.issue_digest,
                    dismiss_until = excluded.dismiss_until,
                    updated_at = excluded.updated_at
                """,
                (scope, issue, until.isoformat(), now.isoformat(), now.isoformat()),
            )
            db.commit()
        return until

    def evaluate(self, state: dict, remediation_path: str, now: datetime) -> dict | None:
        """Return a canonical notice when Captain should surface one, otherwise None.

        Important unresolved problems reappear after dismissal expiry and immediately when the
        issue changes. Ready connectors automatically clear persisted notice state.
        """
        validate_connector_state(state)
        now = _aware(now, "now")
        if state["ready"]:
            self.clear_if_resolved(state)
            return None

        scope = self._scope_digest(state)
        issue = self._issue_digest(state)
        dismiss_until = None
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT issue_digest, dismiss_until FROM connector_notices WHERE scope_digest = ?",
                (scope,),
            ).fetchone()
            if row is not None and row[0] == issue and row[1] is not None:
                try:
                    parsed = datetime.fromisoformat(row[1])
                except (TypeError, ValueError) as exc:
                    raise ContractError("persisted dismiss") from exc
                if parsed.tzinfo is None:
                    raise ContractError("persisted dismiss")
                dismiss_until = parsed

        notice = build_notice(state, remediation_path, now, dismiss_until=dismiss_until)
        if notice is None:
            return None
        surface = should_surface(notice, state, now)

        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                INSERT INTO connector_notices(scope_digest, issue_digest, dismiss_until, last_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scope_digest) DO UPDATE SET
                    issue_digest = excluded.issue_digest,
                    dismiss_until = CASE
                        WHEN connector_notices.issue_digest = excluded.issue_digest
                        THEN connector_notices.dismiss_until
                        ELSE NULL
                    END,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                (scope, issue, dismiss_until.isoformat() if dismiss_until else None, now.isoformat(), now.isoformat()),
            )
            db.commit()

        if not surface:
            return None
        # Regenerate without a stale dismissal so the surfaced payload reflects actionable state.
        return build_notice(state, remediation_path, now, dismiss_until=None)

    def persisted_rows(self) -> list[tuple]:
        """Testing/Doctor projection; contains digests and timestamps only."""
        with sqlite3.connect(self.path) as db:
            return db.execute(
                "SELECT scope_digest, issue_digest, dismiss_until, last_seen_at, updated_at FROM connector_notices ORDER BY scope_digest"
            ).fetchall()
