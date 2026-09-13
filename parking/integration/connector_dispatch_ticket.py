from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json

from connector_authorization_gate import ConnectorAuthorizationError, authorize_connector_action


class ConnectorDispatchTicketError(ValueError):
    pass


MAX_TTL_SECONDS = 30
MAX_CLOCK_SKEW_SECONDS = 5


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ConnectorDispatchTicketError(f"invalid {name}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConnectorDispatchTicketError(f"invalid {name}") from exc
    if parsed.tzinfo is None:
        raise ConnectorDispatchTicketError(f"naive {name}")
    return parsed.astimezone(timezone.utc)


def _text(value: object, name: str, max_len: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_len or value.strip() != value:
        raise ConnectorDispatchTicketError(f"invalid {name}")
    return value


def _ticket_id(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    return sha256(encoded).hexdigest()


def issue_dispatch_ticket(
    envelope: dict,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    connector_id: str,
    action: str,
    request_id: str,
    issued_at: str,
    expires_at: str,
) -> dict:
    """Issue a short-lived authorization ticket bound to the exact scoped connector state.

    The ticket contains metadata only. It performs no provider call and carries no credentials.
    """
    request_id = _text(request_id, "request_id", 120)
    issued = _utc(issued_at, "issued_at")
    expires = _utc(expires_at, "expires_at")
    ttl = (expires - issued).total_seconds()
    if ttl <= 0 or ttl > MAX_TTL_SECONDS:
        raise ConnectorDispatchTicketError("invalid ttl")

    try:
        decision = authorize_connector_action(
            envelope,
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            connector_id=connector_id,
            action=action,
        )
    except ConnectorAuthorizationError as exc:
        raise ConnectorDispatchTicketError("authorization denied") from exc

    binding_digest = envelope.get("binding_digest")
    if not isinstance(binding_digest, str) or len(binding_digest) != 64:
        raise ConnectorDispatchTicketError("invalid state binding")

    payload = {
        "schema_version": 1,
        "chat_id": _text(chat_id, "chat_id", 120),
        "project_id": _text(project_id, "project_id", 120),
        "repo_scope": _text(repo_scope, "repo_scope", 300),
        "connector_id": decision["connector_id"],
        "action": decision["action"],
        "permission": decision["permission"],
        "request_id": request_id,
        "state_binding_digest": binding_digest,
        "issued_at": issued.isoformat(),
        "expires_at": expires.isoformat(),
    }
    return {**payload, "ticket_id": _ticket_id(payload)}


def consume_dispatch_ticket(
    ticket: dict,
    envelope: dict,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    connector_id: str,
    action: str,
    request_id: str,
    now: str,
    consumed_ticket_ids: set[str],
) -> dict:
    """Revalidate one ticket immediately before provider dispatch and mark it single-use."""
    expected_keys = {
        "schema_version", "chat_id", "project_id", "repo_scope", "connector_id",
        "action", "permission", "request_id", "state_binding_digest", "issued_at",
        "expires_at", "ticket_id",
    }
    if not isinstance(ticket, dict) or set(ticket) != expected_keys or ticket["schema_version"] != 1:
        raise ConnectorDispatchTicketError("invalid ticket")
    if not isinstance(consumed_ticket_ids, set):
        raise ConnectorDispatchTicketError("invalid consumption ledger")

    payload = {key: ticket[key] for key in expected_keys if key != "ticket_id"}
    expected_id = _ticket_id(payload)
    actual_id = ticket["ticket_id"]
    if not isinstance(actual_id, str) or not hmac.compare_digest(actual_id, expected_id):
        raise ConnectorDispatchTicketError("ticket tampered")
    if actual_id in consumed_ticket_ids:
        raise ConnectorDispatchTicketError("ticket already consumed")

    if ticket["chat_id"] != chat_id or ticket["project_id"] != project_id or ticket["repo_scope"] != repo_scope:
        raise ConnectorDispatchTicketError("scope mismatch")
    if ticket["connector_id"] != connector_id or ticket["action"] != action or ticket["request_id"] != request_id:
        raise ConnectorDispatchTicketError("dispatch mismatch")

    issued = _utc(ticket["issued_at"], "issued_at")
    expires = _utc(ticket["expires_at"], "expires_at")
    current = _utc(now, "now")
    if (issued - current).total_seconds() > MAX_CLOCK_SKEW_SECONDS:
        raise ConnectorDispatchTicketError("ticket from future")
    if current > expires:
        raise ConnectorDispatchTicketError("ticket expired")
    ttl = (expires - issued).total_seconds()
    if ttl <= 0 or ttl > MAX_TTL_SECONDS:
        raise ConnectorDispatchTicketError("invalid ttl")

    current_binding = envelope.get("binding_digest")
    if not isinstance(current_binding, str) or not hmac.compare_digest(current_binding, ticket["state_binding_digest"]):
        raise ConnectorDispatchTicketError("connector state changed")

    try:
        decision = authorize_connector_action(
            envelope,
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            connector_id=connector_id,
            action=action,
        )
    except ConnectorAuthorizationError as exc:
        raise ConnectorDispatchTicketError("authorization no longer valid") from exc
    if decision["permission"] != ticket["permission"]:
        raise ConnectorDispatchTicketError("permission changed")

    consumed_ticket_ids.add(actual_id)
    return {
        "authorized": True,
        "ticket_id": actual_id,
        "connector_id": connector_id,
        "action": action,
        "request_id": request_id,
    }
