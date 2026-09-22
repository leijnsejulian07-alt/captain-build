from __future__ import annotations

import json
import re
from pathlib import Path

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
ALLOWED_CHECKS = {"unit", "doctor", "router", "project_isolation", "repo_isolation"}
TOP_LEVEL_KEYS = {"schema_version", "generated_on", "source_repository", "required_local_checks", "external_prerequisites", "components"}
COMPONENT_KEYS = {"id", "pr", "depends_on"}


def load_manifest(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_manifest(data)
    return data


def validate_manifest(data: dict) -> None:
    if not isinstance(data, dict) or set(data) != TOP_LEVEL_KEYS:
        raise ValueError("manifest must contain the exact schema fields")
    if data.get("schema_version") != 1:
        raise ValueError("unsupported schema_version")
    source_repository = data.get("source_repository")
    if not isinstance(source_repository, str) or not REPO_RE.fullmatch(source_repository) or ".." in source_repository:
        raise ValueError("invalid source_repository")
    generated_on = data.get("generated_on")
    if not isinstance(generated_on, str) or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", generated_on):
        raise ValueError("invalid generated_on")
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
    if any(not isinstance(c, dict) or set(c) != COMPONENT_KEYS for c in components):
        raise ValueError("component entries must contain exact fields")
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
        deps = component["depends_on"]
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
    graph = {c["id"]: [d for d in c["depends_on"] if d in component_ids] for c in data["components"]}
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
