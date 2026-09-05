# Captain OSS Scout — 2026-09-05

Daily scan focus: project-scoped memory/context and isolated builder execution.

## Strong candidate: dukememory
- Capability: local-first project-scoped agent memory, reviewable pending memories, hybrid retrieval, code context, audit/backup/eval tools.
- License: MIT-compatible use should be confirmed from repository before any integration decision.
- Fit: strong architectural reference for project isolation, review-before-recall, supersede/archive semantics, and secret blocking.
- Resource cost: PostgreSQL + pgvector + Ollama make direct adoption heavier than Captain's current lightweight memory path.
- Decision: ADAPT PATTERNS, do not install. Keep Captain Project State/epoch as authority.

## Candidate: Meterless context engines
- Capability: local-first context/world-state/reasoning engines.
- License: Apache-2.0 for the open-source engines.
- Fit: potentially useful as a future retrieval/context subsystem behind Captain.
- Risk/cost: broader platform scope and immature runtime roadmap; avoid introducing a second control-plane.
- Decision: WATCH / selectively borrow retrieval ideas only.

## Builder references
Limboo/Alera/Agetor remain useful worktree/session UX references. No new install action.
Worktrees remain concurrency boundaries, not security boundaries; Captain still requires scope ownership + runtime/filesystem/network sandboxing.

## Reconciliation note
Fallback branch: automation/memory-scope-regression-20260905
Commit 68acb62545eef64af68a895ae0b6d1659c559308 parks Router/test_scope_pair_http.py.
When laptop writes/execution are available, copy/review the test into the real AI Workspace, run it against the local router, then run memory epoch smoke + Doctor + OpenBuilder regressions before treating it as locally integrated.
