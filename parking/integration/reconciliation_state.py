from __future__ import annotations

import json
import re
from pathlib import Path

ALLOWED_STATES = {"pending", "verified", "integrated", "rejected"}
REQUIRED_CHECKS = {"unit", "doctor", "router", "project_isolation", "repo_isolation"}
COMPONENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def load_state(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"schema_version": 1, "components": {}}
    data = json.loads(p.read_text(encoding="utf-8"))
    validate_state(data)
    return data


def _validate_checks(checks: object) -> None:
    if not isinstance(checks, dict) or set(checks) != REQUIRED_CHECKS:
        raise ValueError("verified/integrated state requires exact acceptance checks")
    if any(value != "passed" for value in checks.values()):
        raise ValueError("verified/integrated state requires passing checks")


def validate_state(data: dict) -> None:
    if not isinstance(data, dict) or set(data) != {"schema_version", "components"} or data.get("schema_version") != 1:
        raise ValueError("invalid reconciliation state")
    components = data.get("components")
    if not isinstance(components, dict) or len(components) > 128:
        raise ValueError("invalid component state map")
    for component_id, row in components.items():
        if not isinstance(component_id, str) or not COMPONENT_ID_RE.fullmatch(component_id) or not isinstance(row, dict):
            raise ValueError("invalid component state entry")
        state = row.get("state")
        if state not in ALLOWED_STATES:
            raise ValueError("invalid component lifecycle state")
        allowed_keys = {"state", "checks"} if state in {"verified", "integrated"} else {"state"}
        if set(row) != allowed_keys:
            raise ValueError("unexpected component state fields")
        if state in {"verified", "integrated"}:
            _validate_checks(row.get("checks"))


def transition(data: dict, component_id: str, new_state: str, checks: dict | None = None) -> dict:
    validate_state(data)
    if new_state not in ALLOWED_STATES or not isinstance(component_id, str) or not COMPONENT_ID_RE.fullmatch(component_id):
        raise ValueError("invalid transition")
    current = data["components"].get(component_id, {"state": "pending"})["state"]
    allowed = {"pending": {"verified", "rejected"}, "verified": {"integrated", "rejected"}, "integrated": set(), "rejected": set()}
    if new_state not in allowed[current]:
        raise ValueError("non-monotonic transition")
    if new_state in {"verified", "integrated"}:
        _validate_checks(checks)
    elif checks is not None:
        raise ValueError("checks only allowed for verified/integrated state")
    next_data = json.loads(json.dumps(data))
    row = {"state": new_state}
    if checks is not None:
        row["checks"] = dict(checks)
    next_data["components"][component_id] = row
    validate_state(next_data)
    return next_data
