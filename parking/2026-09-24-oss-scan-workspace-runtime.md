# Captain OSS scan — 2026-09-24

## Decision
Prioritize a **Limboo-style workspace adapter pattern**, not Limboo as a second control-plane. Do not install or execute third-party code yet.

## Strong candidate: Limboo
- MIT licensed, local-first Electron/React/TypeScript workspace.
- Useful proven subsystem ideas: per-session git worktrees, repository-resume delta, provider-neutral agent adapters, shared authorization core, local SQLite/FTS5 memory/search, checkpoints, PTY services, guarded filesystem, typed IPC.
- Fit for Captain: high for builder/repo/session isolation and resume/reality checks.
- Integration rule: Captain remains sole router/orchestrator. Reuse/adapt bounded subsystems or patterns only; never run Limboo as an independent agent/router daemon.
- Resource fit: local SQLite/FTS5 avoids an embeddings service; Electron duplication is undesirable, so prefer extracting/adapting subsystem concepts rather than embedding the whole desktop shell.
- Security: promising documented posture (argv-only git/process spawning, path/symlink guards, sender validation, safeStorage, redaction), but code-level audit is required before reuse.

## Secondary candidates
- sandboxd (MIT): useful preview/sandbox API ideas, but container isolation and API auth off by default make it unsuitable for untrusted multi-tenant execution without hardening. Consider only behind Captain's existing authority/epoch walls.
- octo-agent (MIT): interesting reusable SKILL.md compatibility, MCP OAuth/tool-search, recycle-bin rollback and browser CDP patterns. Avoid its agent/router layer because Captain already owns that control-plane.
- VoltAgent: useful eval/observability/workflow ideas, but avoid introducing a duplicate orchestration runtime.

## Next testable implementation
Add a provider-neutral **Repo Reality / Resume Delta** contract behind Captain/OpenBuilder. On builder/session resume, compare the current repo identity + HEAD + worktree status against the last Captain checkpoint under the same `chat_id + project_id + repo_scope + epoch`. If authority or epoch differs, fail closed. If repo state drifted, emit a bounded structured delta before the next build action. Never auto-merge or auto-run repo-authored commands.

Acceptance regressions:
1. Same authority + unchanged repo resumes with empty delta.
2. Same authority + changed HEAD/files produces bounded delta.
3. Stale epoch cannot read/use prior resume snapshot.
4. Different project/chat/repo_scope cannot access another snapshot.
5. Symlink/path escape and oversized delta fail closed.
6. Normal non-project chat remains unaffected.

Sources reviewed today: GitHub project pages/search, Reddit search, official/project documentation surfaced for current coding-agent/workspace/sandbox systems. No third-party code installed or executed.
