from __future__ import annotations

import json
import re
from pathlib import Path

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ALLOWED_CHECKS = {"unit", "doctor", "router", "project_isolation", "repo_isolation"}


def load_manifest(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_manifest(data)
    return data


def validate_manifest(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("manifest must be an object")
    if data.get("schema_version") != 1:
        raise ValueError("unsupported schema_version")
    checks = data.get("required_local_checks")
    if not isinstance(checks, list) or set(checks) != ALLOWED_CHECKS or len(checks) != len(ALLOWED_CHECKS):
        raise ValueError("required_local_checks must contain the exact acceptance set")
    external = data.get("external_prerequisites", [])
    _validate_ids(external, "external prerequisite")
    if len(set(external)) != len(external):
        raise ValueError("duplicate external prerequisite")
    components = data.get("components")
    if not isinstance(components, list) or not components or len(components) > 128:
        raise ValueError("components must be a bounded non-empty list")
    if any(not isinstance(c, dict) for c in components):
        raise ValueError("component entries must be objects")
    ids = [c.get("id") for c in components]
    _validate_ids(ids, "component")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate component id")
    if set(ids) & set(external):
        raise ValueError("component/external prerequisite id collision")
    prs = [c.get("pr") for c in components]
    if any(type(p) is not int or p < 1 or p > 1000000 for p in prs) or len(set(prs)) != len(prs):
        raise ValueError("invalid or duplicate PR number")
    known = set(ids) | set(external)
    component_ids = set(ids)
    graph: dict[str, list[str]] = {}
    for component in components:
        deps = component.get("depends_on", [])
        if not isinstance(deps, list) or len(deps) > 32:
            raise ValueError("invalid dependency list")
        _validate_ids(deps, "dependency")
        if len(set(deps)) != len(deps) or component["id"] in deps:
            raise ValueError("duplicate/self dependency")
        if any(dep not in known for dep in deps):
            raise ValueError("unknown dependency")
        graph[component["id"]] = [d for d in deps if d in component_ids]
    _toposort(graph)


def integration_order(data: dict) -> list[str]:
    validate_manifest(data)
    component_ids = {x["id"] for x in data["components"]}
    graph = {c["id"]: [d for d in c.get("depends_on", []) if d in component_ids] for c in data["components"]}
    return _toposort(graph)


def _validate_ids(values: list, label: str) -> None:
    if not isinstance(values, list) or any(not isinstance(v, str) or not ID_RE.fullmatch(v) for v in values):
        raise ValueError(f"invalid {label} id")


def _toposort(graph: dict[str, list[str]]) -> list[str]:
    result: list[str] = []
    temporary: set[str] = set()
    permanent: set[str] = set()
    def visit(node: str) -> None:
        if node in permanent:
            return
        if node in temporary:
            raise ValueError("dependency cycle")
        temporary.add(node)
        for dep in graph[node]:
            visit(dep)
        temporary.remove(node)
        permanent.add(node)
        result.append(node)
    for node in sorted(graph):
        visit(node)
    return result
