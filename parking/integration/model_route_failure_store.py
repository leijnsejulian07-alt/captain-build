from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Mapping

from model_route_failure_policy import RouteFailurePolicyError, parse_failure_state


class RouteFailureStoreError(ValueError):
    pass


_RECEIPT_FIELDS = {
    "schema_version",
    "provider_id",
    "model_id",
    "failure_kind",
    "clear_authorized",
    "observed_at_ms",
    "secret_fields",
}


@dataclass(frozen=True)
class ClearResult:
    provider_id: str
    model_id: str
    cleared: bool


class RouteFailureStore:
    """Own exact provider/model failure state and clear it atomically after recovery.

    Recovery receipts are intentionally not bearer tokens. The caller must also present
    the exact failure-state snapshot that was used to obtain the receipt. Under the store
    lock, Captain compares that snapshot with the currently stored state before deletion.
    If a newer failure replaced it in the meantime, deletion fails closed instead of a
    stale Test Connection result erasing fresh routing evidence.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._states: dict[tuple[str, str], dict[str, object]] = {}

    @staticmethod
    def _copy_state(state: Mapping[str, object]) -> dict[str, object]:
        try:
            parsed = parse_failure_state(state)
        except RouteFailurePolicyError as exc:
            raise RouteFailureStoreError("invalid failure state") from exc
        return {
            "provider_id": parsed.provider_id,
            "model_id": parsed.model_id,
            "failure_kind": parsed.failure_kind,
            "disposition": parsed.disposition,
            "consecutive_failures": parsed.consecutive_failures,
            "observed_at_ms": parsed.observed_at_ms,
            "retry_not_before_ms": parsed.retry_not_before_ms,
        }

    def put(self, state: Mapping[str, object]) -> None:
        normalized = self._copy_state(state)
        key = (str(normalized["provider_id"]), str(normalized["model_id"]))
        with self._lock:
            previous = self._states.get(key)
            if previous is not None and int(normalized["observed_at_ms"]) <= int(previous["observed_at_ms"]):
                raise RouteFailureStoreError("failure state must advance monotonically")
            self._states[key] = normalized

    def get(self, provider_id: str, model_id: str) -> dict[str, object] | None:
        key = (provider_id, model_id)
        with self._lock:
            state = self._states.get(key)
            return None if state is None else dict(state)

    @staticmethod
    def _validate_receipt(receipt: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(receipt, Mapping) or set(receipt) != _RECEIPT_FIELDS:
            raise RouteFailureStoreError("invalid recovery receipt schema")
        if receipt.get("schema_version") != 1 or receipt.get("clear_authorized") is not True:
            raise RouteFailureStoreError("recovery receipt not authorized")
        if receipt.get("secret_fields") != []:
            raise RouteFailureStoreError("recovery receipt contains secret fields")
        provider = receipt.get("provider_id")
        model = receipt.get("model_id")
        kind = receipt.get("failure_kind")
        observed = receipt.get("observed_at_ms")
        for value, name in ((provider, "provider_id"), (model, "model_id"), (kind, "failure_kind")):
            if not isinstance(value, str) or not value or len(value) > 128 or any(ch.isspace() for ch in value):
                raise RouteFailureStoreError(f"invalid receipt {name}")
        if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
            raise RouteFailureStoreError("invalid receipt observed_at_ms")
        return dict(receipt)

    def clear_after_recovery(
        self,
        *,
        receipt: Mapping[str, object],
        expected_failure_state: Mapping[str, object],
    ) -> ClearResult:
        authorized = self._validate_receipt(receipt)
        expected = self._copy_state(expected_failure_state)
        key = (str(expected["provider_id"]), str(expected["model_id"]))

        if (authorized["provider_id"], authorized["model_id"]) != key:
            raise RouteFailureStoreError("recovery receipt route mismatch")
        if authorized["failure_kind"] != expected["failure_kind"]:
            raise RouteFailureStoreError("recovery receipt failure kind mismatch")
        if int(authorized["observed_at_ms"]) <= int(expected["observed_at_ms"]):
            raise RouteFailureStoreError("recovery evidence is not newer than failure")

        with self._lock:
            current = self._states.get(key)
            if current is None:
                raise RouteFailureStoreError("route failure state missing")
            if current != expected:
                raise RouteFailureStoreError("route failure state changed before recovery clear")
            del self._states[key]

        return ClearResult(provider_id=key[0], model_id=key[1], cleared=True)
