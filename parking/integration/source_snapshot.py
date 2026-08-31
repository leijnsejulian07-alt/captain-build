from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COMPONENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ALLOWED_PR_STATES = {"open", "closed"}
MAX_COMPONENTS = 128


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ValueError("invalid commit sha")
    return value


def validate_observed_sources(manifest: dict, observed: dict) -> dict:
    if not isinstance(manifest, dict) or not isinstance(observed, dict):
        raise ValueError("manifest and observed sources must be objects")
    components = manifest.get("components")
    if not isinstance(components, list) or len(components) > MAX_COMPONENTS:
        raise ValueError("invalid manifest components")

    expected: dict[str, int] = {}
    for row in components:
        if not isinstance(row, dict):
            raise ValueError("invalid component record")
        component_id = row.get("id")
        pr = row.get("pr")
        if not isinstance(component_id, str) or not COMPONENT_ID_RE.fullmatch(component_id):
            raise ValueError("invalid component id")
        if not isinstance(pr, int) or pr <= 0 or component_id in expected:
            raise ValueError("invalid component pr mapping")
        expected[component_id] = pr

    if set(observed) != set(expected):
        raise ValueError("observed source set must exactly match manifest components")

    normalized: dict[str, dict] = {}
    for component_id, expected_pr in expected.items():
        row = observed[component_id]
        if not isinstance(row, dict) or set(row) != {"pr", "state", "head_sha", "base_sha"}:
            raise ValueError("invalid observed source record")
        if row["pr"] != expected_pr:
            raise ValueError("observed PR does not match manifest")
        if row["state"] not in ALLOWED_PR_STATES:
            raise ValueError("invalid PR state")
        normalized[component_id] = {
            "pr": expected_pr,
            "state": row["state"],
            "head_sha": _sha(row["head_sha"]),
            "base_sha": _sha(row["base_sha"]),
        }
    return normalized


def _manifest_binding(manifest: dict) -> dict:
    """Return the planning-critical manifest subset bound into source evidence."""
    components = manifest.get("components")
    if not isinstance(components, list):
        raise ValueError("invalid manifest components")
    bound_components = []
    for row in components:
        if not isinstance(row, dict):
            raise ValueError("invalid component record")
        deps = row.get("depends_on", [])
        if not isinstance(deps, list):
            raise ValueError("invalid component dependencies")
        bound_components.append({"id": row.get("id"), "pr": row.get("pr"), "depends_on": sorted(deps)})
    return {
        "schema_version": manifest.get("schema_version"),
        "required_local_checks": sorted(manifest.get("required_local_checks", [])),
        "external_prerequisites": sorted(manifest.get("external_prerequisites", [])),
        "components": sorted(bound_components, key=lambda row: str(row["id"])),
    }


def source_snapshot_digest(manifest: dict, observed: dict) -> str:
    normalized = validate_observed_sources(manifest, observed)
    payload = {"schema_version": 2, "manifest": _manifest_binding(manifest), "sources": normalized}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assert_snapshot_unchanged(manifest: dict, planned: dict, current: dict, expected_digest: str) -> None:
    if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise ValueError("invalid source snapshot digest")
    planned_digest = source_snapshot_digest(manifest, planned)
    current_digest = source_snapshot_digest(manifest, current)
    if planned_digest != expected_digest:
        raise ValueError("planned source snapshot evidence or manifest was modified")
    if current_digest != expected_digest:
        raise ValueError("parked source PRs or manifest changed after reconciliation planning")
    if any(row["state"] != "open" for row in current.values()):
        raise ValueError("all parked source PRs must remain open until local verification")
