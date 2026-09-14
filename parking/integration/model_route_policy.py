from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


SCHEMA_VERSION = 1
_ALLOWED_COST_CLASSES = {"free", "local", "paid"}
_ALLOWED_HEALTH = {"healthy", "degraded", "unavailable"}
_ALLOWED_TASKS = {"chat", "research", "coding", "vision", "tool_use", "long_context"}


class RoutePolicyError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderCandidate:
    provider_id: str
    model_id: str
    cost_class: str
    health: str
    enabled: bool
    ready: bool
    capabilities: frozenset[str]
    priority: int


def _token(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise RoutePolicyError(f"invalid {name}")
    if any(ch.isspace() for ch in value):
        raise RoutePolicyError(f"invalid {name}")
    return value


def parse_candidate(value: Mapping[str, object]) -> ProviderCandidate:
    required = {
        "provider_id", "model_id", "cost_class", "health", "enabled", "ready",
        "capabilities", "priority",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise RoutePolicyError("invalid provider candidate schema")
    provider_id = _token(value.get("provider_id"), "provider_id")
    model_id = _token(value.get("model_id"), "model_id")
    cost_class = value.get("cost_class")
    health = value.get("health")
    enabled = value.get("enabled")
    ready = value.get("ready")
    capabilities = value.get("capabilities")
    priority = value.get("priority")
    if cost_class not in _ALLOWED_COST_CLASSES:
        raise RoutePolicyError("invalid cost_class")
    if health not in _ALLOWED_HEALTH:
        raise RoutePolicyError("invalid health")
    if not isinstance(enabled, bool) or not isinstance(ready, bool):
        raise RoutePolicyError("enabled/ready must be bool")
    if isinstance(capabilities, (str, bytes)) or not isinstance(capabilities, Sequence):
        raise RoutePolicyError("capabilities must be a sequence")
    parsed_caps = frozenset(_token(item, "capability") for item in capabilities)
    if not parsed_caps or not parsed_caps.issubset(_ALLOWED_TASKS):
        raise RoutePolicyError("invalid capabilities")
    if isinstance(priority, bool) or not isinstance(priority, int) or priority < 0 or priority > 1000:
        raise RoutePolicyError("invalid priority")
    return ProviderCandidate(
        provider_id=provider_id,
        model_id=model_id,
        cost_class=cost_class,
        health=health,
        enabled=enabled,
        ready=ready,
        capabilities=parsed_caps,
        priority=priority,
    )


def choose_route(
    candidates: Sequence[Mapping[str, object]],
    *,
    task: str,
    allow_paid: bool = False,
    excluded_routes: Sequence[tuple[str, str]] = (),
) -> dict[str, object]:
    """Return a deterministic Captain-owned route decision.

    Paid providers are never eligible unless allow_paid=True is explicitly supplied by
    the caller. Disabled, unready or unavailable providers are never selected. Degraded
    providers are fallback-only behind healthy candidates. The returned projection is
    deliberately secret-free and carries enough reason metadata for observability.
    """
    task_name = _token(task, "task")
    if task_name not in _ALLOWED_TASKS:
        raise RoutePolicyError("unsupported task")
    if not isinstance(allow_paid, bool):
        raise RoutePolicyError("allow_paid must be bool")
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise RoutePolicyError("candidates must be a sequence")

    parsed = [parse_candidate(candidate) for candidate in candidates]
    route_ids = [(item.provider_id, item.model_id) for item in parsed]
    if len(route_ids) != len(set(route_ids)):
        raise RoutePolicyError("duplicate provider/model route")

    excluded = set()
    for pair in excluded_routes:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise RoutePolicyError("invalid excluded route")
        excluded.add((_token(pair[0], "provider_id"), _token(pair[1], "model_id")))

    rejected: list[dict[str, str]] = []
    eligible: list[ProviderCandidate] = []
    for candidate in parsed:
        route_key = (candidate.provider_id, candidate.model_id)
        reason = None
        if route_key in excluded:
            reason = "already_attempted"
        elif not candidate.enabled:
            reason = "disabled"
        elif not candidate.ready:
            reason = "not_ready"
        elif candidate.health == "unavailable":
            reason = "unavailable"
        elif task_name not in candidate.capabilities:
            reason = "missing_capability"
        elif candidate.cost_class == "paid" and not allow_paid:
            reason = "paid_not_authorized"
        if reason is not None:
            rejected.append({"provider_id": candidate.provider_id, "model_id": candidate.model_id, "reason": reason})
        else:
            eligible.append(candidate)

    if not eligible:
        return {
            "schema_version": SCHEMA_VERSION,
            "task": task_name,
            "selected": None,
            "rejected": sorted(rejected, key=lambda item: (item["provider_id"], item["model_id"])),
            "reason": "no_eligible_route",
            "paid_authorized": allow_paid,
            "secret_fields": [],
        }

    cost_rank = {"local": 0, "free": 1, "paid": 2}
    health_rank = {"healthy": 0, "degraded": 1}
    selected = min(
        eligible,
        key=lambda item: (
            health_rank[item.health],
            cost_rank[item.cost_class],
            item.priority,
            item.provider_id,
            item.model_id,
        ),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "task": task_name,
        "selected": {
            "provider_id": selected.provider_id,
            "model_id": selected.model_id,
            "cost_class": selected.cost_class,
            "health": selected.health,
        },
        "rejected": sorted(rejected, key=lambda item: (item["provider_id"], item["model_id"])),
        "reason": "selected",
        "paid_authorized": allow_paid,
        "secret_fields": [],
    }
