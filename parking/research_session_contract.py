"""Provider-neutral, fail-closed research session contract for Captain."""
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit
import re

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_ALLOWED_PROVIDERS = {"web", "github", "reddit", "youtube", "rss", "tavily", "other"}


def _stable_id(value: str, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value) or ".." in value:
        raise ValueError(f"invalid {name}")
    return value


def _scope_hash(repo_scope: str) -> str:
    if not isinstance(repo_scope, str) or not repo_scope.strip():
        raise ValueError("repo_scope required")
    return sha256(repo_scope.strip().encode()).hexdigest()


def canonical_http_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("invalid url")
    p = urlsplit(value.strip())
    if p.scheme.lower() not in {"http", "https"} or not p.hostname or p.username or p.password:
        raise ValueError("http(s) url required")
    host = p.hostname.lower()
    port = p.port
    netloc = host if port is None else f"{host}:{port}"
    path = p.path or "/"
    return urlunsplit((p.scheme.lower(), netloc, path, p.query, ""))


@dataclass(frozen=True)
class ResearchSession:
    session_id: str
    project_id: str
    repo_scope_hash: str
    query_hash: str
    max_sources: int

    @classmethod
    def create(cls, session_id: str, project_id: str, repo_scope: str, query: str, max_sources: int = 20):
        _stable_id(session_id, "session_id")
        _stable_id(project_id, "project_id")
        if not isinstance(query, str) or not query.strip() or len(query) > 4096:
            raise ValueError("invalid query")
        if isinstance(max_sources, bool) or not isinstance(max_sources, int) or not 1 <= max_sources <= 50:
            raise ValueError("invalid max_sources")
        return cls(session_id, project_id, _scope_hash(repo_scope), sha256(query.strip().encode()).hexdigest(), max_sources)

    def permits(self, project_id: str, repo_scope: str) -> bool:
        return project_id == self.project_id and _scope_hash(repo_scope) == self.repo_scope_hash


def normalize_sources(session: ResearchSession, sources: list[dict]) -> list[dict]:
    if not isinstance(sources, list):
        raise ValueError("sources must be list")
    out, seen = [], set()
    for item in sources:
        if not isinstance(item, dict):
            continue
        provider = item.get("provider")
        if provider not in _ALLOWED_PROVIDERS:
            continue
        try:
            url = canonical_http_url(item.get("url", ""))
        except (ValueError, TypeError):
            continue
        if url in seen:
            continue
        title = item.get("title", "")
        retrieved_at = item.get("retrieved_at", "")
        if not isinstance(title, str) or len(title) > 512 or not isinstance(retrieved_at, str) or len(retrieved_at) > 64:
            continue
        seen.add(url)
        out.append({"provider": provider, "url": url, "title": title, "retrieved_at": retrieved_at})
        if len(out) >= session.max_sources:
            break
    return out
