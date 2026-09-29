# Builder result epoch/owner acceptance contract

Status: fallback design only; not locally integrated or verified.

Goal: make asynchronous OpenBuilder/Builder results fail closed at the Captain server boundary, not only in browser state.

A submitted Builder result must carry the immutable owner tuple captured when work started: chat_id, project_id, repo_scope, Project State epoch, and builder_session_id. Before any result can update files, preview, console, diff, task state, memory, or UI, Captain must resolve the current authoritative tuple and require exact equality. Missing fields, malformed epochs, stale epochs, changed repo scope, changed chat/project, or replaced Builder sessions are rejection conditions. Rejection must not expose result payload content to the new scope.

Required regressions:
1. exact owner tuple is accepted;
2. changing each tuple field independently rejects the result;
3. epoch increment rejects an otherwise identical result;
4. a late result after chat/project/repo switch cannot mutate files, preview, console, diff, memory, task status, or notifications;
5. normal non-project chat remains unaffected;
6. rejected result logs contain only safe identifiers/reason codes, never payloads or secrets;
7. retry/resume creates a new owner tuple rather than reusing stale authority.

Integration rule: keep this check behind Captain's existing single control-plane and existing Project State authority. Do not add another router or daemon. Reconcile against the live B310 implementation before merging and run Doctor/router/OpenBuilder/memory-context regressions locally.

Rollback: this document/branch is inert until intentionally integrated.
