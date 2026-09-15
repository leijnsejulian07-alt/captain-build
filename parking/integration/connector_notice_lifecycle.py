from __future__ import annotations

from datetime import datetime

from connector_settings_contract import (
    ContractError,
    connector_problem_fingerprint,
    should_surface,
    validate_connector_state,
)


LIFECYCLE_STATES = {"visible", "temporarily_dismissed", "resolved"}


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ContractError("now")
    return value


def project_notice_lifecycle(state: dict, notice: dict | None, now: datetime) -> dict:
    """Project one connector problem into Captain's secret-free banner lifecycle.

    This is deliberately pure and side-effect free. Persistence/auth/network actions stay in their
    existing subsystems. The browser can consume this projection without guessing why a notice is
    visible, suppressed, or cleared.
    """
    validate_connector_state(state)
    now = _aware(now)

    if state["ready"]:
        return {
            "schema_version": 1,
            "status": "resolved",
            "reason": "connector_ready",
            "show_banner": False,
            "reminder_at": None,
            "remediation_path": None,
            "secret_fields": [],
        }

    if notice is None:
        return {
            "schema_version": 1,
            "status": "visible",
            "reason": "action_required",
            "show_banner": True,
            "reminder_at": None,
            "remediation_path": None,
            "secret_fields": [],
        }

    surface = should_surface(notice, state, now)
    current_fingerprint = connector_problem_fingerprint(state)
    remediation_path = notice["remediation_path"]

    if notice["notice_fingerprint"] != current_fingerprint:
        return {
            "schema_version": 1,
            "status": "visible",
            "reason": "problem_changed",
            "show_banner": True,
            "reminder_at": None,
            "remediation_path": remediation_path,
            "secret_fields": [],
        }

    dismiss_until = notice["dismiss_until"]
    if dismiss_until is None:
        reason = "action_required"
        reminder_at = None
    else:
        parsed = datetime.fromisoformat(dismiss_until)
        if parsed.tzinfo is None:
            raise ContractError("dismiss")
        reminder_at = parsed.isoformat()
        reason = "reminder_due" if surface else "temporarily_dismissed"

    return {
        "schema_version": 1,
        "status": "visible" if surface else "temporarily_dismissed",
        "reason": reason,
        "show_banner": bool(surface),
        "reminder_at": reminder_at,
        "remediation_path": remediation_path,
        "secret_fields": [],
    }
