"""Pure, dependency-free sanitizer for Captain research -> Project State metadata.
Parking code: reconcile with live Project State API before runtime integration.
"""
from __future__ import annotations
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit

MAX_QUERIES = 3
MAX_SOURCES = 10
MAX_TITLE = 240


def _text(value, limit):
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def canonical_http_url(value):
    if not isinstance(value, str):
        return None
    try:
        p = urlsplit(value.strip())
    except ValueError:
        return None
    if p.scheme.lower() not in {"http", "https"} or not p.netloc:
        return None
    host = (p.hostname or "").lower()
    if not host:
        return None
    port = f":{p.port}" if p.port and not ((p.scheme == "http" and p.port == 80) or (p.scheme == "https" and p.port == 443)) else ""
    return urlunsplit((p.scheme.lower(), host + port, p.path or "/", p.query, ""))


def build_research_state(*, project_id, repo_scope, bundle):
    """Return metadata-only state or None. Never raises on malformed research data."""
    if not isinstance(project_id, str) or not project_id.strip():
        return None
    if not isinstance(repo_scope, str) or not repo_scope.strip():
        return None
    if not isinstance(bundle, dict):
        return None

    queries = [_text(q, 300) for q in bundle.get("queries", [])[:MAX_QUERIES] if _text(q, 300)]
    safe, seen = [], set()
    for src in bundle.get("sources", [])[:MAX_SOURCES * 2]:
        if not isinstance(src, dict):
            continue
        url = canonical_http_url(src.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        matched = [_text(q, 300) for q in src.get("matched_queries", [])[:MAX_QUERIES] if _text(q, 300)]
        score = src.get("score")
        score = score if isinstance(score, (int, float)) and not isinstance(score, bool) else None
        safe.append({
            "title": _text(src.get("title"), MAX_TITLE),
            "url": url,
            "provider": _text(src.get("provider"), 80),
            "retrieved_at": _text(src.get("retrieved_at"), 64),
            "matched_queries": matched,
            "score": score,
        })
        if len(safe) >= MAX_SOURCES:
            break

    hosts = sorted({urlsplit(s["url"]).hostname for s in safe})
    return {
        "schema": "captain.research_provenance.v1",
        "repo_scope_hash": sha256(repo_scope.strip().encode()).hexdigest(),
        "queries": queries,
        "sources": safe,
        "source_count": len(safe),
        "host_count": len(hosts),
    }
