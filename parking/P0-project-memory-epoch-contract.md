# P0 — Project Memory / Context Epoch Contract

Status: parking implementation contract; not locally integrated or verified.

## Invariant

Project-scoped memory/context is addressable only by the complete scope tuple:

`chat_id + project_id + repo_scope + project_state_epoch`.

A project memory/context read MUST fail closed if any scoped field is missing, mismatched, stale, malformed, or cannot be compared to the current Project State. Never fall back to another project, repo, chat, or earlier epoch.

Normal non-project chat remains supported through an explicitly separate unscoped/global-chat path. It must not query project memory stores implicitly.

## Required behavior

- Stamp every project memory/context write with the current immutable epoch.
- Resolve current Project State before project-scoped reads and compare all four scope fields.
- Epoch change immediately makes prior-epoch project memory/context inaccessible to normal retrieval; retention/GC may happen later.
- Builder sessions, tasks and research context may reference memory only through the same scope tuple.
- Shared distilled learning is permitted only through an explicit sanitization/promotion path that strips project identifiers, repository material, secrets and project-specific content.
- Missing/unknown epoch is denial, not compatibility mode.
- Logs/telemetry may record denial reason codes and opaque scope hashes, never memory contents or secrets.

## Regression matrix

1. Same chat/project/repo/current epoch => readable.
2. Same everything but stale epoch => denied.
3. Same epoch but different project => denied.
4. Same epoch/project but different repo_scope => denied.
5. Same project/repo but different chat where memory is chat-scoped => denied.
6. Missing epoch on project read => denied.
7. Background task created under epoch N cannot read memory after Project State advances to N+1.
8. Builder session from epoch N cannot hydrate context after N+1.
9. Search/retrieval cannot return stale-epoch chunks even when semantic similarity is highest.
10. Normal non-project chat still reads/writes its explicit non-project memory path and never receives project memory.
11. Distilled shared learning cannot contain project/repo/chat identifiers or source payloads.
12. Cache keys include the complete scope tuple and epoch; stale cache entries cannot satisfy current reads.

## Integration gate

Do not mark complete until local tests prove the matrix above, existing router/task/OpenBuilder regressions remain green, Doctor is run, and no compatibility shim silently widens scope. Reconcile this contract against the live implementation before coding because the GitHub fallback may lag the laptop.

## Rollback

This parking document is isolated on a branch and changes no runtime code. Delete the branch if the live implementation already satisfies or supersedes the contract.
