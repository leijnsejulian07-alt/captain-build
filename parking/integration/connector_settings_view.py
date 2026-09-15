from __future__ import annotations

from datetime import datetime
from typing import Iterable

from connector_health_runtime import connector_status_view
from connector_settings_contract import ContractError, validate_connector_state


_ACTIONS_BY_AUTH = {
    "oauth": ("connect", "test_connection"),
    "api_key": ("configure_credentials", "test_connection"),
    "id": ("configure_identifier", "test_connection"),
    "local": ("test_connection",),
    "none": ("test_connection",),
}


def _clean_path(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("settings://connectors/") or len(value) > 200:
        raise ContractError("remediation path")
    return value


def _action_set(state: dict) -> list[dict]:
    actions: list[dict] = []
    if not state["installed"]:
        actions.append({"id": "install", "requires_user_action": True, "may_activate_paid_service": False})
        return actions

    for action in _ACTIONS_BY_AUTH[state["auth_method"]]:
        if action == "connect" and state["connected"]:
            continue
        if action in {"configure_credentials", "configure_identifier"} and state["connected"]:
            continue
        actions.append({"id": action, "requires_user_action": True, "may_activate_paid_service": False})

    actions.append(
        {
            "id": "disable" if state["enabled"] else "enable",
            "requires_user_action": True,
            "may_activate_paid_service": False,
        }
    )
    return actions


def build_connector_settings_view(
    state: dict,
    *,
    remediation_path: str,
    active_notice: dict | None = None,
) -> dict:
    """Create the canonical secret-free Settings card for one connector.

    The projection is deliberately passive: action descriptors never execute auth, reveal
    credentials, enable providers, or permit paid activation. Provider adapters remain behind
    explicit Captain Settings actions.
    """
    validate_connector_state(state)
    remediation = _clean_path(remediation_path)
    status = connector_status_view(state)

    if active_notice is not None:
        required_notice = {
            "schema_version",
            "connector_id",
            "project_id",
            "issue_code",
            "notice_fingerprint",
            "remediation_path",
            "dismiss_until",
            "secret_fields",
        }
        if not isinstance(active_notice, dict) or set(active_notice) != required_notice:
            raise ContractError("notice schema")
        if active_notice["connector_id"] != state["connector_id"] or active_notice["project_id"] != state["project_id"]:
            raise ContractError("notice scope mismatch")
        if active_notice["remediation_path"] != remediation or active_notice["secret_fields"] != []:
            raise ContractError("notice mismatch")
        if state["ready"]:
            raise ContractError("ready connector cannot surface notice")

    return {
        "schema_version": 1,
        "connector_id": state["connector_id"],
        "project_id": state["project_id"],
        "status": {
            "installed": status["installed"],
            "connected": status["connected"],
            "enabled": status["enabled"],
            "ready": status["ready"],
            "health": status["health"],
        },
        "auth_method": status["auth_method"],
        "permissions": status["permissions"],
        "issue_code": status["issue_code"],
        "actions": _action_set(state),
        "remediation_path": remediation,
        "notice": active_notice,
        "paid_activation_allowed": False,
        "secret_fields": [],
    }


def build_connector_launch_projection(
    states: Iterable[dict],
    *,
    remediation_paths: dict[str, str],
    notices: dict[str, dict | None] | None = None,
) -> dict:
    """Build the app-launch connector projection from canonical per-project states.

    Connector IDs must be unique inside the supplied project scope. This prevents duplicate or
    conflicting cards from hiding an unhealthy state during launch.
    """
    notice_map = notices or {}
    cards: list[dict] = []
    seen: set[tuple[str, str]] = set()
    projects: set[str] = set()

    for state in states:
        validate_connector_state(state)
        key = (state["project_id"], state["connector_id"])
        if key in seen:
            raise ContractError("duplicate connector state")
        seen.add(key)
        projects.add(state["project_id"])
        if state["connector_id"] not in remediation_paths:
            raise ContractError("missing remediation path")
        cards.append(
            build_connector_settings_view(
                state,
                remediation_path=remediation_paths[state["connector_id"]],
                active_notice=notice_map.get(state["connector_id"]),
            )
        )

    cards.sort(key=lambda card: (card["project_id"], card["connector_id"]))
    return {
        "schema_version": 1,
        "projects": sorted(projects),
        "connectors": cards,
        "unresolved_count": sum(1 for card in cards if not card["status"]["ready"]),
        "secret_fields": [],
    }
