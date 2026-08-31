from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ALLOWED_STATES = {"pending", "verified", "integrated", "rejected"}
REQUIRED_CHECKS = {"unit", "doctor", "router", "project_isolation", "repo_isolation"}
COMPONENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_VERSION = 4
MAX_VERIFICATION_AGE = timedelta(minutes=30)
MAX_FUTURE_SKEW = timedelta(minutes=1)


def _parse_time(value: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid acceptance evidence timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid acceptance evidence timestamp") from exc
    if dt.tzinfo is None:
        raise ValueError("acceptance evidence timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_state(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"schema_version": SCHEMA_VERSION, "local_base_sha": None, "components": {}}
    data = json.loads(p.read_text(encoding="utf-8"))
    validate_state(data)
    return data


def _validate_checks(checks: object) -> None:
    if not isinstance(checks, dict) or set(checks) != REQUIRED_CHECKS:
        raise ValueError("verified/integrated state requires exact acceptance checks")
    if any(value != "passed" for value in checks.values()):
        raise ValueError("verified/integrated state requires passing checks")


def _validate_sha(value: object, *, allow_none: bool = False) -> None:
    if allow_none and value is None:
        return
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ValueError("invalid git sha")


def _evidence_digest(component_id: str, base_sha: str, checks: dict, verified_at: str) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "component_id": component_id,
        "local_base_sha": base_sha,
        "checks": checks,
        "verified_at": verified_at,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_verification_freshness(verified_at: str, now_dt: datetime) -> None:
    verified_dt = _parse_time(verified_at)
    if verified_dt > now_dt + MAX_FUTURE_SKEW:
        raise ValueError("acceptance evidence timestamp is in the future")
    if now_dt - verified_dt > MAX_VERIFICATION_AGE:
        raise ValueError("acceptance evidence is expired")


def validate_state(data: dict, *, now: str | None = None) -> None:
    required = {"schema_version", "local_base_sha", "components"}
    if not isinstance(data, dict) or set(data) != required or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid reconciliation state")
    _validate_sha(data.get("local_base_sha"), allow_none=True)
    now_dt = datetime.now(timezone.utc) if now is None else _parse_time(now)
    components = data.get("components")
    if not isinstance(components, dict) or len(components) > 128:
        raise ValueError("invalid component state map")
    for component_id, row in components.items():
        if not isinstance(component_id, str) or not COMPONENT_ID_RE.fullmatch(component_id) or not isinstance(row, dict):
            raise ValueError("invalid component state entry")
        state = row.get("state")
        if state not in ALLOWED_STATES:
            raise ValueError("invalid component lifecycle state")
        allowed_keys = {"state", "checks", "verified_base_sha", "verified_at", "evidence_digest"} if state in {"verified", "integrated"} else {"state"}
        if set(row) != allowed_keys:
            raise ValueError("unexpected component state fields")
        if state in {"verified", "integrated"}:
            _validate_checks(row.get("checks"))
            _validate_sha(row.get("verified_base_sha"))
            if row["verified_base_sha"] != data["local_base_sha"]:
                raise ValueError("component verification is stale for local base")
            verified_at = row.get("verified_at")
            _parse_time(verified_at)
            if state == "verified":
                _validate_verification_freshness(verified_at, now_dt)
            digest = row.get("evidence_digest")
            if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
                raise ValueError("invalid acceptance evidence digest")
            expected = _evidence_digest(component_id, row["verified_base_sha"], row["checks"], verified_at)
            if digest != expected:
                raise ValueError("acceptance evidence was modified")


def set_local_base(data: dict, local_base_sha: str) -> dict:
    validate_state(data)
    _validate_sha(local_base_sha)
    if any(row["state"] in {"verified", "integrated"} for row in data["components"].values()):
        raise ValueError("cannot change local base after verification")
    next_data = json.loads(json.dumps(data))
    next_data["local_base_sha"] = local_base_sha
    validate_state(next_data)
    return next_data


def transition(
    data: dict,
    component_id: str,
    new_state: str,
    checks: dict | None = None,
    *,
    now: str | None = None,
) -> dict:
    now_dt = datetime.now(timezone.utc) if now is None else _parse_time(now)
    now_iso = _iso(now_dt)
    validate_state(data, now=now_iso)
    if new_state not in ALLOWED_STATES or not isinstance(component_id, str) or not COMPONENT_ID_RE.fullmatch(component_id):
        raise ValueError("invalid transition")
    current_row = data["components"].get(component_id, {"state": "pending"})
    current = current_row["state"]
    allowed = {"pending": {"verified", "rejected"}, "verified": {"integrated", "rejected"}, "integrated": set(), "rejected": set()}
    if new_state not in allowed[current]:
        raise ValueError("non-monotonic transition")
    if new_state == "verified":
        _validate_checks(checks)
        _validate_sha(data.get("local_base_sha"))
        verified_at = now_iso
    elif new_state == "integrated":
        _validate_checks(checks)
        _validate_sha(data.get("local_base_sha"))
        if current_row.get("verified_base_sha") != data["local_base_sha"] or checks != current_row.get("checks"):
            raise ValueError("integration requires unchanged verified evidence")
        _validate_verification_freshness(current_row.get("verified_at"), now_dt)
        verified_at = current_row["verified_at"]
    elif checks is not None:
        raise ValueError("checks only allowed for verified/integrated state")
    else:
        verified_at = None
    next_data = json.loads(json.dumps(data))
    row = {"state": new_state}
    if checks is not None:
        row["checks"] = dict(checks)
        row["verified_base_sha"] = data["local_base_sha"]
        row["verified_at"] = verified_at
        row["evidence_digest"] = _evidence_digest(component_id, data["local_base_sha"], row["checks"], verified_at)
    next_data["components"][component_id] = row
    validate_state(next_data, now=now_iso)
    return next_data
