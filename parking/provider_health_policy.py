from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Iterable

ALLOWED_POLICIES = {"local-only", "free-cloud", "approved-paid"}
ALLOWED_STATES = {"healthy", "degraded", "rate_limited", "auth_failed", "offline"}


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderState:
    provider_id: str
    state: str
    success_rate: float
    latency_ms: int
    cooldown_until: int
    is_local: bool
    is_free: bool
    paid: bool
    paid_approved: bool = False

    def __post_init__(self) -> None:
        if not self.provider_id or len(self.provider_id) > 64 or any(c in self.provider_id for c in "/\\.."):
            raise PolicyError("invalid provider id")
        if self.state not in ALLOWED_STATES:
            raise PolicyError("invalid provider state")
        if not 0.0 <= self.success_rate <= 1.0:
            raise PolicyError("invalid success rate")
        if not 0 <= self.latency_ms <= 300_000:
            raise PolicyError("invalid latency")
        if self.cooldown_until < 0:
            raise PolicyError("invalid cooldown")
        if self.paid and self.is_free:
            raise PolicyError("provider cannot be both paid and free")
        if self.paid_approved and not self.paid:
            raise PolicyError("approval only applies to paid providers")

    def usable(self, policy: str, now: int | None = None) -> bool:
        if policy not in ALLOWED_POLICIES:
            raise PolicyError("unknown routing policy")
        now = int(time()) if now is None else int(now)
        if self.state in {"auth_failed", "offline"} or self.cooldown_until > now:
            return False
        if policy == "local-only":
            return self.is_local
        if policy == "free-cloud":
            return self.is_local or self.is_free
        return self.is_local or self.is_free or (self.paid and self.paid_approved)

    def score(self, now: int | None = None) -> float:
        now = int(time()) if now is None else int(now)
        if self.state in {"auth_failed", "offline"} or self.cooldown_until > now:
            return float("-inf")
        state_penalty = {"healthy": 0.0, "degraded": 0.25, "rate_limited": 0.7}[self.state]
        latency_penalty = min(self.latency_ms / 20_000.0, 0.5)
        locality_bonus = 0.08 if self.is_local else 0.0
        free_bonus = 0.04 if self.is_free else 0.0
        return self.success_rate - state_penalty - latency_penalty + locality_bonus + free_bonus


def choose_provider(providers: Iterable[ProviderState], policy: str, now: int | None = None) -> ProviderState:
    if policy not in ALLOWED_POLICIES:
        raise PolicyError("unknown routing policy")
    candidates = [p for p in providers if p.usable(policy, now)]
    if not candidates:
        raise PolicyError("no provider satisfies policy and health gates")
    return max(candidates, key=lambda p: (p.score(now), p.is_local, p.is_free, p.provider_id))


def cooldown_for_failure(kind: str, attempts: int) -> int:
    if attempts < 1 or attempts > 8:
        raise PolicyError("invalid attempt count")
    base = {"rate_limit": 60, "timeout": 20, "server_error": 15, "auth": 3600}.get(kind)
    if base is None:
        raise PolicyError("unknown failure kind")
    return min(base * (2 ** (attempts - 1)), 3600)


def public_route_metadata(provider: ProviderState, policy: str) -> dict:
    if policy not in ALLOWED_POLICIES:
        raise PolicyError("unknown routing policy")
    return {
        "provider_id": provider.provider_id,
        "policy": policy,
        "health": provider.state,
        "local": provider.is_local,
        "free": provider.is_free,
        "paid_used": bool(provider.paid and provider.paid_approved),
    }
