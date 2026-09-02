from __future__ import annotations

from connector_settings_contract import ContractError, validate_connector_state
from connector_state_scope import ConnectorStateScopeError, unwrap_connector_state


class ConnectorAuthorizationError(ValueError):
    pass


ACTION_PERMISSION = {
    "read": "read",
    "write": "write",
    "admin": "admin",
    "repo": "repo",
    "calendar": "calendar",
    "mail": "mail",
    "files": "files",
    "browser": "browser",
}


def authorize_connector_action(
    envelope: dict,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    connector_id: str,
    action: str,
) -> dict:
    """Authorize one connector execution against Captain's canonical scoped state.

    This is an execution gate, not a Connect/Test Connection flow. It never performs
    authentication, network access, secret lookup, or provider calls. Callers must pass
    this gate immediately before dispatching a connector action.
    """
    if action not in ACTION_PERMISSION:
        raise ConnectorAuthorizationError("unknown action")
    if not isinstance(connector_id, str) or not connector_id or len(connector_id) > 80 or connector_id.strip() != connector_id:
        raise ConnectorAuthorizationError("invalid connector_id")

    try:
        state = unwrap_connector_state(
            envelope,
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
        )
        validate_connector_state(state)
    except (ConnectorStateScopeError, ContractError) as exc:
        raise ConnectorAuthorizationError("invalid scoped connector state") from exc

    if state["connector_id"] != connector_id:
        raise ConnectorAuthorizationError("connector mismatch")
    if not state["installed"]:
        raise ConnectorAuthorizationError("connector not installed")
    if not state["connected"]:
        raise ConnectorAuthorizationError("connector not connected")
    if not state["enabled"]:
        raise ConnectorAuthorizationError("connector disabled")
    if not state["ready"]:
        raise ConnectorAuthorizationError("connector not ready")
    if state["health"] != "healthy":
        raise ConnectorAuthorizationError("connector unhealthy")

    required_permission = ACTION_PERMISSION[action]
    if required_permission not in state["permissions_granted"]:
        raise ConnectorAuthorizationError("permission not granted")
    if required_permission not in state["permissions_required"]:
        raise ConnectorAuthorizationError("action outside configured permission set")

    return {
        "authorized": True,
        "connector_id": connector_id,
        "project_id": project_id,
        "repo_scope": repo_scope,
        "action": action,
        "permission": required_permission,
    }
