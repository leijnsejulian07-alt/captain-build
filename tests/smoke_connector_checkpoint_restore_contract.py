"""Regression for connector UI checkpoint persistence/restoration."""
from src.captain.connector_event_bridge import ConnectorEventBridge
from src.captain.connector_event_checkpoint import validate_connector_checkpoint
from src.captain.connector_settings import AuthMethod, ConnectorError, ConnectorHealth, ConnectorSettingsRegistry, ConnectorState

def main() -> None:
    registry = ConnectorSettingsRegistry()
    registry.put(ConnectorState(connector_id="github", project_id=None, installed=True, connected=True, enabled=True, auth_method=AuthMethod.OAUTH, permissions=frozenset({"repo:read"}), required_permissions=frozenset({"repo:read"}), health=ConnectorHealth.AUTH_INVALID, auth_material_present=True))
    bridge = ConnectorEventBridge(registry)
    bridge.reconcile("github", project_id=None, now=0)
    checkpoint = bridge.checkpoint()
    restored = ConnectorEventBridge(registry, checkpoint=checkpoint)
    # Unchanged canonical state after restart must not duplicate status/open events.
    assert restored.reconcile("github", project_id=None, now=1) == ()
    assert restored.checkpoint() == checkpoint

    bad = dict(checkpoint)
    bad["token"] = "never"
    try:
        validate_connector_checkpoint(bad)
        raise AssertionError("unknown secret-bearing field accepted")
    except ConnectorError:
        pass

    injected = {"sequence": 0, "last_status": [{"project_id": None, "connector_id": "github", "status": {"api_key": "never"}}], "notice_open": []}
    try:
        ConnectorEventBridge(registry, checkpoint=injected)
        raise AssertionError("nested secret-bearing field accepted")
    except ConnectorError:
        pass

    duplicate = {"sequence": 0, "last_status": [], "notice_open": [
        {"project_id": "a", "connector_id": "x", "open": True},
        {"project_id": "a", "connector_id": "x", "open": False},
    ]}
    try:
        validate_connector_checkpoint(duplicate)
        raise AssertionError("duplicate scoped checkpoint accepted")
    except ConnectorError:
        pass
    print("CONNECTOR_CHECKPOINT_RESTORE_PASS")

if __name__ == "__main__": main()
