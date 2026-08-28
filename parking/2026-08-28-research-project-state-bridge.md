# Captain parking note — research → Project State bridge

Status: NOT APPLIED. This is a parking artifact for the next stable local Captain run.

## Current verified local state
- `Agents/captain_tools.py` already supports provenance-bearing, multi-query research bundles with URL validation, cross-query corroboration and per-host diversity.
- `Agents/project_state.py` persists scoped state by `project_id + canonical repo_scope` and now redacts credential-like values as well as sensitive keys.
- Live Captain remained untouched after the desktop bridge became unstable during this run.

## Proposed next change
Persist only distilled research metadata after a successful `research web:` / `research bundle:` operation when BOTH `project_id` and a valid local `repo_scope` are present.

Persist under a bounded `research` Project State object:
- `last_queries`: max 3 strings, each <= 500 chars
- `last_retrieved_at`: UTC timestamp
- `sources`: max 10 entries containing only `title`, canonical/http(s) `url`, `provider`, `matched_queries`, optional numeric `score`
- `source_count` and `host_count`

Explicitly DO NOT persist:
- snippets / page text / HTML
- Tavily raw responses
- tokens, cookies, auth/session data
- chat_id
- preview/builder/worktree state
- conclusions generated solely from untrusted snippets

## Integration shape
1. Change research rendering internals so normalization returns both rendered text and a safe structured source summary (or add a helper that derives safe metadata before rendering).
2. Extend `captain_tools.handle(...)` with optional `project_id` while preserving current callers.
3. Update the single router call site to pass the existing scoped project header value to `captain_tools.handle`.
4. Only call `project_state.save_state(project_id, repo_scope, {"research": safe_summary})` after provider success and only when both scope values exist.
5. Persistence failure must NOT break the user-visible research result; report/record it as a local non-secret warning only.

## Required tests before activation
- Mock-provider test: stored state contains URL/title/provider/query metadata but no snippet text.
- Secret-value test: a credential-looking title/query is redacted by Project State.
- Scope isolation test: same project_id + repo A cannot read repo B research state.
- Unscoped test: no project_id or repo_scope => no research persistence.
- Failure test: Project State write failure leaves research response intact.
- Python compile of changed modules.
- Existing router regression + isolated capability/plugin/connector regression.
- Doctor after router restart.

## Rollback
Before local edits, copy every changed file to a timestamped `Backups/research-project-state-*` folder. If any acceptance check fails, restore those files and leave this item pending.
