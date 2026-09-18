from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from parking.integration.plugin_dispatch_authority import validate_plugin_dispatch_ticket


def _digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_digest(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


@dataclass
class PluginDispatchRuntime:
    """Captain-owned one-shot dispatch boundary.

    Validation remains delegated to the canonical plugin authority. The runtime
    consumes a validated ticket before returning an execution receipt so a
    capability grant cannot be replayed for a second side effect. Only digests
    are retained; connector secrets, payloads and provider responses never enter
    this ledger.
    """

    consumed: set[str] = field(default_factory=set)

    def authorize_once(
        self,
        ticket: Mapping[str, object],
        records: Sequence[Mapping[str, object]],
        *,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        current_state_epoch: int,
        operation_digest: str,
    ) -> dict[str, object]:
        if not _valid_digest(operation_digest):
            raise ValueError("invalid operation_digest")

        validated = validate_plugin_dispatch_ticket(
            ticket,
            records,
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            current_state_epoch=current_state_epoch,
        )
        ticket_digest = _digest(validated)
        if ticket_digest in self.consumed:
            raise PermissionError("plugin dispatch ticket already consumed")

        # Consume before handing authority to the caller. A caller crash may
        # require a fresh ticket, but can never replay a side-effect grant.
        self.consumed.add(ticket_digest)
        return {
            "schema_version": 1,
            "authorized": True,
            "ticket_digest": ticket_digest,
            "operation_digest": operation_digest,
            "scope": dict(validated["scope"]),
            "state_epoch": validated["state_epoch"],
            "plugin_id": validated["plugin_id"],
            "capability": validated["capability"],
        }

    def receipt_matches(
        self,
        receipt: Mapping[str, object],
        *,
        operation_digest: str,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        current_state_epoch: int,
        plugin_id: str,
        capability: str,
    ) -> bool:
        """Validate a receipt at the actual side-effect boundary.

        A digest match alone is not authority: the caller must prove the same
        chat/project/repository/epoch/plugin/capability scope that was authorized.
        This prevents a valid receipt from being replayed after a Project State
        switch or reused by a different subsystem operation.
        """
        required = {
            "schema_version", "authorized", "ticket_digest", "operation_digest",
            "scope", "state_epoch", "plugin_id", "capability",
        }
        if not isinstance(receipt, Mapping) or set(receipt) != required:
            return False
        if not _valid_digest(operation_digest) or not _valid_digest(receipt.get("ticket_digest")):
            return False
        scope = receipt.get("scope")
        if not isinstance(scope, Mapping) or set(scope) != {"chat_id", "project_id", "repo_scope"}:
            return False
        return (
            receipt.get("schema_version") == 1
            and receipt.get("authorized") is True
            and isinstance(receipt.get("operation_digest"), str)
            and hmac.compare_digest(str(receipt.get("operation_digest")), operation_digest)
            and receipt.get("ticket_digest") in self.consumed
            and scope.get("chat_id") == chat_id
            and scope.get("project_id") == project_id
            and scope.get("repo_scope") == repo_scope
            and receipt.get("state_epoch") == current_state_epoch
            and receipt.get("plugin_id") == plugin_id
            and receipt.get("capability") == capability
        )
