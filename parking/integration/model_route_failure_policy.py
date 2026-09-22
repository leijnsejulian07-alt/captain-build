from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


SCHEMA_VERSION = 1
_ALLOWED_FAILURE_KINDS = {
    "transient",
    "rate_limited",
    "auth_invalid",
    "permission_denied",
    "setup_required",
    "provider_deprecated",
}
_BLOCKING_FAILURES = {
    "auth_invalid",
    "permission_denied",
    "setup_required",
    "provider_deprecated",
}
_BASE_TRANSIENT_COOLDOWN_MS = 15_000
_MAX_TRANSIENT_COOLDOWN_MS = 300_000
_DEFAULT_RATE_LIMIT_COOLDOWN_MS = 60_000
_MAX_RATE_LIMIT_COOLDOWN_MS = 3_600_000


class RouteFailurePolicyError(ValueError):
    pass


@dataclass(frozen=True)
class RouteFailureState:
    provider_id: str
    model_id: str
    failure_kind: str
    disposition: str
    consecutive_failures: int
    observed_at_ms: int
    retry_not_before_ms: int | None


def _token(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise RouteFailurePolicyError(f"invalid {name}")
    if any(ch.isspace() for ch in value):
        raise RouteFailurePolicyError(f"invalid {name}")
    return value


def _timestamp(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RouteFailurePolicyError(f"invalid {name}")
    return value


def _positive_int(value: object, name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise RouteFailurePolicyError(f"invalid {name}")
    return value


def parse_failure_state(value: Mapping[str, object]) -> RouteFailureState:
    required = {
        "provider_id",
        "model_id",
        "failure_kind",
        "disposition",
        "consecutive_failures",
        "observed_at_ms",
        "retry_not_before_ms",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise RouteFailurePolicyError("invalid route failure state schema")

    provider_id = _token(value.get("provider_id"), "provider_id")
    model_id = _token(value.get("model_id"), "model_id")
    failure_kind = value.get("failure_kind")
    disposition = value.get("disposition")
    consecutive_failures = _positive_int(value.get("consecutive_failures"), "consecutive_failures", maximum=1_000_000)
    observed_at_ms = _timestamp(value.get("observed_at_ms"), "observed_at_ms")
    retry_raw = value.get("retry_not_before_ms")

    if failure_kind not in _ALLOWED_FAILURE_KINDS:
        raise RouteFailurePolicyError("invalid failure_kind")
    expected_disposition = "blocked" if failure_kind in _BLOCKING_FAILURES else "cooldown"
    if disposition != expected_disposition:
        raise RouteFailurePolicyError("failure disposition does not match failure_kind")

    if disposition == "blocked":
        if retry_raw is not None:
            raise RouteFailurePolicyError("blocked failures cannot auto-retry")
        retry_not_before_ms = None
    else:
        retry_not_before_ms = _timestamp(retry_raw, "retry_not_before_ms")
        if retry_not_before_ms <= observed_at_ms:
            raise RouteFailurePolicyError("cooldown must extend beyond observation time")

    return RouteFailureState(
        provider_id=provider_id,
        model_id=model_id,
        failure_kind=failure_kind,
        disposition=disposition,
        consecutive_failures=consecutive_failures,
        observed_at_ms=observed_at_ms,
        retry_not_before_ms=retry_not_before_ms,
    )


def _project(state: RouteFailureState) -> dict[str, object]:
    return {
        "provider_id": state.provider_id,
        "model_id": state.model_id,
        "failure_kind": state.failure_kind,
        "disposition": state.disposition,
        "consecutive_failures": state.consecutive_failures,
        "observed_at_ms": state.observed_at_ms,
        "retry_not_before_ms": state.retry_not_before_ms,
    }


def record_route_failure(
    *,
    provider_id: str,
    model_id: str,
    failure_kind: str,
    observed_at_ms: int,
    previous_state: Mapping[str, object] | None = None,
    retry_after_ms: int | None = None,
) -> dict[str, object]:
    """Return a secret-free failure state for one exact provider/model route.

    Transient failures use bounded exponential cooldowns. Rate-limit failures honor an
    explicit retry_after_ms only inside a conservative bound. Auth, permission, setup
    and provider-deprecation failures remain blocked until an explicit successful
    health/test event clears them; Captain never invents or refreshes authorization.
    """
    provider = _token(provider_id, "provider_id")
    model = _token(model_id, "model_id")
    observed = _timestamp(observed_at_ms, "observed_at_ms")
    if failure_kind not in _ALLOWED_FAILURE_KINDS:
        raise RouteFailurePolicyError("invalid failure_kind")

    previous = None
    if previous_state is not None:
        previous = parse_failure_state(previous_state)
        if (previous.provider_id, previous.model_id) != (provider, model):
            raise RouteFailurePolicyError("previous state route mismatch")
        if observed <= previous.observed_at_ms:
            raise RouteFailurePolicyError("failure observation must be monotone")

    streak = 1
    if previous is not None and previous.failure_kind == failure_kind:
        streak = previous.consecutive_failures + 1

    if failure_kind in _BLOCKING_FAILURES:
        if retry_after_ms is not None:
            raise RouteFailurePolicyError("blocking failures cannot accept retry_after_ms")
        disposition = "blocked"
        retry_not_before = None
    elif failure_kind == "rate_limited":
        if retry_after_ms is None:
            cooldown = _DEFAULT_RATE_LIMIT_COOLDOWN_MS
        else:
            cooldown = _positive_int(retry_after_ms, "retry_after_ms", maximum=_MAX_RATE_LIMIT_COOLDOWN_MS)
        disposition = "cooldown"
        retry_not_before = observed + cooldown
    else:
        if retry_after_ms is not None:
            raise RouteFailurePolicyError("transient failures do not accept retry_after_ms")
        exponent = min(streak - 1, 20)
        cooldown = min(_BASE_TRANSIENT_COOLDOWN_MS * (2 ** exponent), _MAX_TRANSIENT_COOLDOWN_MS)
        disposition = "cooldown"
        retry_not_before = observed + cooldown

    return _project(RouteFailureState(
        provider_id=provider,
        model_id=model,
        failure_kind=failure_kind,
        disposition=disposition,
        consecutive_failures=streak,
        observed_at_ms=observed,
        retry_not_before_ms=retry_not_before,
    ))


def route_failure_reason(
    state: Mapping[str, object],
    *,
    now_ms: int,
) -> str | None:
    """Return the routing rejection reason, or None once a cooldown has expired."""
    parsed = parse_failure_state(state)
    now = _timestamp(now_ms, "now_ms")
    if parsed.disposition == "blocked":
        return "provider_blocked"
    if parsed.retry_not_before_ms is None:
        raise RouteFailurePolicyError("cooldown state missing retry boundary")
    if now < parsed.retry_not_before_ms:
        return "provider_cooldown"
    return None


def validate_failure_states(states: Sequence[Mapping[str, object]]) -> dict[tuple[str, str], RouteFailureState]:
    if isinstance(states, (str, bytes)) or not isinstance(states, Sequence):
        raise RouteFailurePolicyError("failure_states must be a sequence")
    parsed: dict[tuple[str, str], RouteFailureState] = {}
    for raw in states:
        state = parse_failure_state(raw)
        key = (state.provider_id, state.model_id)
        if key in parsed:
            raise RouteFailurePolicyError("duplicate route failure state")
        parsed[key] = state
    return parsed


def clear_route_failure_after_success(
    state: Mapping[str, object],
    *,
    provider_id: str,
    model_id: str,
    observed_at_ms: int,
) -> None:
    """Validate an explicit successful probe/call before the caller removes state.

    Returning None is intentional: the owning store should delete the exact route state
    only after this validation succeeds. This avoids keeping provider response bodies,
    credentials or other sensitive success payloads in routing state.
    """
    parsed = parse_failure_state(state)
    provider = _token(provider_id, "provider_id")
    model = _token(model_id, "model_id")
    observed = _timestamp(observed_at_ms, "observed_at_ms")
    if (parsed.provider_id, parsed.model_id) != (provider, model):
        raise RouteFailurePolicyError("success route mismatch")
    if observed <= parsed.observed_at_ms:
        raise RouteFailurePolicyError("success observation must be monotone")
