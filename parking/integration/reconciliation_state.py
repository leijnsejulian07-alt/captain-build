from __future__ import annotations

import json
from pathlib import Path

ALLOWED_STATES = {"pending", "verified", "integrated", "rejected"}


def load_state(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"schema_version": 1, "components": {}}
    data = json.loads(p.read_text(encoding="utf-8"))
    validate_state(data)
    return data


def validate_state(data: dict) -> None:
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("invalid reconciliation state")
    components = data.get("components")
    if not isinstance(components, dict) or len(components) > 128:
        raise ValueError("invalid component state map")
    for component_id, row in components.items():
        if not isinstance(component_id, str) or not isinstance(row, dict):
            raise ValueError("invalid component state entry")
        if row.get("state") not in ALLOWED_STATES:
            raise ValueError("invalid component lifecycle state")
        if row.get("state") in {"verified", "integrated"}:
            checks = row.get("checks")
            if not isinstance(checks, dict) or not checks or any(v != "passed" for v in checks.values()):
                raise ValueError("verified/integrated state requires passing checks")


def transition(data: dict, component_id: str, new_state: str, checks: dict | None = None) -> dict:
    validate_state(data)
    if new_state not in ALLOWED_STATES or not component_id:
        raise ValueError("invalid transition")
    current = data["components"].get(component_id, {"state": "pending"})["state"]
    allowed = {"pending": {"verified", "rejected"}, "verified": {"integrated", "rejected"}, "integrated": set(), "rejected": set()}
    if new_state not in allowed[current]:
        raise ValueError("non-monotonic transition")
    next_data = json.loads(json.dumps(data))
    row = {"state": new_state}
    if checks is not None:
        row["checks"] = checks
    next_data["components"][component_id] = row
    validate_state(next_data)
    return next_data
