"""Persist safe automation continuity metadata for Captain fallback reconciliation.

This module stores only coarse operational timestamps/status. It intentionally
stores no prompts, credentials, chat/project IDs, repo paths, or provider data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1
MAX_EXPECTED_INTERVAL_SECONDS = 24 * 60 * 60
MAX_TOLERANCE_SECONDS = 6 * 60 * 60
_ALLOWED_KEYS = {"schema_version", "last_started_at", "last_completed_at", "last_status"}
_ALLOWED_STATUS = {"running", "completed", "partial", "blocked_transient"}
_TERMINAL_STATUS = _ALLOWED_STATUS - {"running"}


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_checkpoint(state: dict[str, Any] | None) -> dict[str, Any]:
    if state is None:
        return {"schema_version": SCHEMA_VERSION}
    if not isinstance(state, dict) or set(state) - _ALLOWED_KEYS:
        raise ValueError("malformed checkpoint")
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported checkpoint schema")

    started = state.get("last_started_at")
    completed = state.get("last_completed_at")
    status = state.get("last_status")
    if status is not None and status not in _ALLOWED_STATUS:
        raise ValueError("invalid run status")

    started_dt = _parse_utc(started) if started is not None else None
    completed_dt = _parse_utc(completed) if completed is not None else None
    if completed_dt is not None and (started_dt is None or completed_dt < started_dt):
        raise ValueError("invalid completion ordering")

    # A checkpoint is either pristine, actively running, or terminal. Reject
    # contradictory/partial combinations so reconnect never invents history.
    if status is None:
        if started is not None or completed is not None:
            raise ValueError("timestamp without run status")
    elif status == "running":
        if started is None or completed is not None:
            raise ValueError("invalid running checkpoint")
    else:
        if started is None or completed is None:
            raise ValueError("terminal checkpoint requires completion")

    return dict(state)


def begin_run(
    prior: dict[str, Any] | None,
    started_at: str,
    *,
    expected_interval_seconds: int = 3600,
    tolerance_seconds: int = 900,
) -> tuple[dict[str, Any], dict[str, Any]]:
    state = validate_checkpoint(prior)
    if not isinstance(expected_interval_seconds, int) or not 60 <= expected_interval_seconds <= MAX_EXPECTED_INTERVAL_SECONDS:
        raise ValueError("invalid expected interval")
    if not isinstance(tolerance_seconds, int) or not 0 <= tolerance_seconds <= MAX_TOLERANCE_SECONDS:
        raise ValueError("invalid tolerance")
    now = _parse_utc(started_at)
    previous = state.get("last_started_at")
    gap_seconds = 0
    if previous is not None:
        previous_dt = _parse_utc(previous)
        if now <= previous_dt:
            raise ValueError("run timestamp must be monotonic")
        gap_seconds = int((now - previous_dt).total_seconds())
    threshold = expected_interval_seconds + tolerance_seconds
    gap_detected = previous is not None and gap_seconds > threshold
    interrupted_prior_run = state.get("last_status") == "running"
    next_state = {
        "schema_version": SCHEMA_VERSION,
        "last_started_at": _iso(now),
        "last_status": "running",
    }
    return next_state, {
        "resume_from_checkpoint": previous is not None,
        "gap_detected": gap_detected,
        "gap_seconds": gap_seconds if gap_detected else 0,
        "interrupted_prior_run": interrupted_prior_run,
    }


def finish_run(state: dict[str, Any], completed_at: str, status: str) -> dict[str, Any]:
    current = validate_checkpoint(state)
    if current.get("last_status") != "running" or "last_started_at" not in current:
        raise ValueError("no running checkpoint")
    if status not in _TERMINAL_STATUS:
        raise ValueError("invalid terminal status")
    completed = _parse_utc(completed_at)
    started = _parse_utc(current["last_started_at"])
    if completed < started:
        raise ValueError("completion before start")
    return {
        "schema_version": SCHEMA_VERSION,
        "last_started_at": current["last_started_at"],
        "last_completed_at": _iso(completed),
        "last_status": status,
    }
