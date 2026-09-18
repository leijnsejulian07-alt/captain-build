# Captain OSS scout follow-up — 2026-09-02

Fresh builder-focused scan only. No third-party code was installed or executed.

## preset-io/agor
- Capability: self-hosted browser workspace for multiple coding-agent CLIs/SDKs, with isolated git branches/workdirs, per-branch dev environments, conversation history, structured tool output, token/cost accounting and MCP control.
- Captain fit: strong reference for the interactive builder pane and branch/session UX. Its orchestration layer must not become a second Captain router/control-plane.
- Integration posture: evaluate UI/session and branch-isolation patterns first; if adopted, use a thin optional adapter behind Captain-owned project/session state.
- Resource/security review still required locally before any install.

## bscott/aio-agent-sandbox
- Capability: Apache-2.0 all-in-one Docker sandbox combining browser, shell, files, MCP and VS Code Server.
- Captain fit: potentially useful optional disposable preview/runtime backend because the interface surface closely matches Captain builder needs.
- Cost/risk: Docker is materially heavier than the laptop-first default, and bundling many services enlarges the attack/dependency surface.
- Integration posture: candidate adapter only, disabled by default; benchmark startup/RAM/disk and audit image/dependencies/egress before adoption.

## limboo-ai/limboo
- Capability: MIT-licensed, local-first Electron/React/TypeScript workspace around coding agents, with per-session git worktrees, guarded filesystem/git/PTY services, local SQLite memory/search, resume-time repository delta detection, one shared authorization core, MCP platform services, integrated terminal/diffs/tasks and a provider-adapter seam.
- Captain fit: unusually strong architecture reference because it deliberately keeps the workspace/control services provider-neutral while agents remain replaceable. Its verified-resume pipeline, single worktree execution root, shared permission core and app-owned durable memory directly overlap Captain's desired builder/state model.
- Interoperability: do not adopt Limboo as a second orchestrator. Prefer extracting/adapting narrow patterns or components behind Captain's existing control-plane: verified resume/repo-delta logic, worktree-root resolution, IPC/security boundaries, local FTS/BM25 memory/search, and provider-neutral service interfaces.
- License/maintenance: MIT. The project advertises current release v1.7.0 and Windows/macOS/Linux builds, but published desktop builds are currently unsigned; treat source/build provenance as preferable to blindly installing binaries.
- Dependencies/resource cost: Electron 42 + React 19 + better-sqlite3 + node-pty + chokidar is materially heavier than a small native/background service. Before adoption, benchmark idle RAM/startup/disk and avoid duplicating Captain's existing Electron/router/process layers.
- Security posture worth borrowing: renderer kept UI-only, typed contextBridge IPC, deny-by-default web permissions, argv-only git/process spawn, path traversal/symlink guards, parameterized SQLite, secret redaction/safeStorage, and a provider-neutral OS sandbox floor.
- Integration posture: high-priority architecture/reference candidate; no install. First compare its resume/worktree/memory contracts against Captain's parked scoped session/context contracts and selectively adapt only what reduces implementation risk or code volume.

## Decision
Nothing was installed. Agor remains a useful UX/branch-session reference; AIO Sandbox remains an optional heavier runtime-adapter candidate. Limboo is the strongest new architecture reference found in this follow-up because its provider-neutral workspace, verified resume, worktree isolation and app-owned memory map closely to Captain without requiring another model router. Captain remains the authoritative user-facing orchestrator and source of project/session truth.
