from __future__ import annotations

import hashlib
import json
from typing import Mapping

SCHEMA_VERSION = 1
TERMINAL_PHASES = frozenset({"complete", "blocked", "cancelled"})
PHASES = frozenset({"plan", "build", "test", "review", "debug", "preview", *TERMINAL_PHASES})
_ALLOWED_TRANSITIONS = {
    "plan": frozenset({"build", "blocked", "cancelled"}),
    "build": frozenset({"test", "debug", "blocked", "cancelled"}),
    "test": frozenset({"review", "debug", "blocked", "cancelled"}),
    "review": frozenset({"preview", "debug", "complete", "blocked", "cancelled"}),
    "debug": frozenset({"build", "test", "review", "blocked", "cancelled"}),
    "preview": frozenset({"review", "debug", "complete", "blocked", "cancelled"}),
    "complete": frozenset(),
    "blocked": frozenset(),
    "cancelled": frozenset(),
}
_DIGEST_KEYS = (
    "schema_version",
    "session_binding_digest",
    "state_epoch",
    "phase",
    "attempt",
    "last_result",
)


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"invalid {field}")
    return value


def _payload(state: Mapping[str, object]) -> dict[str, object]:
    return {key: state[key] for key in _DIGEST_KEYS}


def new_builder_loop(*, session: Mapping[str, object]) -> dict[str, object]:
    """Create a Captain-owned plan→build→test→review/debug→preview loop.

    Only opaque builder-session authority is persisted. Raw chat/project/repo ids,
    prompts, source code and secrets are intentionally excluded.
    """
    binding = _validate_digest(session.get("binding_digest"), "session binding")
    epoch = session.get("state_epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1:
        raise ValueError("invalid state epoch")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "session_binding_digest": binding,
        "state_epoch": epoch,
        "phase": "plan",
        "attempt": 1,
        "last_result": "pending",
    }
    return {**payload, "loop_digest": _digest(payload)}


def authorize_builder_loop(
    state: Mapping[str, object], *, session: Mapping[str, object], state_epoch: int
) -> dict[str, object]:
    required = {*_DIGEST_KEYS, "loop_digest"}
    if not isinstance(state, Mapping) or set(state) != required:
        raise ValueError("invalid builder loop schema")
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported builder loop schema")
    binding = _validate_digest(state.get("session_binding_digest"), "session binding")
    current_binding = _validate_digest(session.get("binding_digest"), "current session binding")
    if binding != current_binding:
        raise PermissionError("builder loop session changed")
    session_epoch = session.get("state_epoch")
    if isinstance(state_epoch, bool) or not isinstance(state_epoch, int) or state_epoch < 1:
        raise ValueError("invalid current state epoch")
    if session_epoch != state_epoch or state.get("state_epoch") != state_epoch:
        raise PermissionError("builder loop Project State epoch changed")
    phase = state.get("phase")
    if phase not in PHASES:
        raise ValueError("invalid builder loop phase")
    attempt = state.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("invalid builder loop attempt")
    if state.get("last_result") not in {"pending", "pass", "fail", "blocked", "cancelled"}:
        raise ValueError("invalid builder loop result")
    loop_digest = _validate_digest(state.get("loop_digest"), "loop digest")
    if loop_digest != _digest(_payload(state)):
        raise ValueError("builder loop was modified")
    return dict(state)


def transition_builder_loop(
    state: Mapping[str, object], *, session: Mapping[str, object], state_epoch: int,
    next_phase: str, result: str
) -> dict[str, object]:
    current = authorize_builder_loop(state, session=session, state_epoch=state_epoch)
    phase = current["phase"]
    if phase in TERMINAL_PHASES:
        raise PermissionError("terminal builder loop cannot transition")
    if next_phase not in _ALLOWED_TRANSITIONS[phase]:
        raise PermissionError(f"invalid builder loop transition: {phase}->{next_phase}")
    if result not in {"pass", "fail", "blocked", "cancelled"}:
        raise ValueError("invalid transition result")
    if next_phase == "complete" and result != "pass":
        raise PermissionError("complete requires passing result")
    if next_phase == "blocked" and result != "blocked":
        raise PermissionError("blocked phase requires blocked result")
    if next_phase == "cancelled" and result != "cancelled":
        raise PermissionError("cancelled phase requires cancelled result")
    if result == "fail" and next_phase not in {"debug", "build", "test", "review"}:
        raise PermissionError("failed work must return to a corrective phase")

    attempt = current["attempt"] + (1 if next_phase in {"build", "test", "review", "debug"} else 0)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "session_binding_digest": current["session_binding_digest"],
        "state_epoch": state_epoch,
        "phase": next_phase,
        "attempt": attempt,
        "last_result": result,
    }
    return {**payload, "loop_digest": _digest(payload)}
