# Captain OSS Scout — 2026-09-12

Daily scan focus: safe builder execution, project isolation, reusable coding subsystems, and interactive tool UI.

## Priority candidate: Docker Sandboxes (`sbx`)
- Source: official Docker documentation, checked 2026-09-12.
- Capability: isolated microVM per coding-agent sandbox, dedicated filesystem/network/Docker daemon, project workspace sharing, credential proxying, network policy, supported agents including Codex/Claude/Gemini/OpenCode.
- Windows fit: official docs list Windows 11 + Windows Hypervisor Platform; Docker Desktop is not required for `sbx`.
- Control-plane fit: strong if Captain owns sandbox lifecycle and passes only a scoped project workspace; do not allow `sbx` or an underlying agent to become a second router/orchestrator.
- Security fit: prefer clone/read-only workspace mode where possible; network deny by default; credentials through host-side proxy/official OAuth only; never inject raw secrets into agent prompts or files.
- Resource cost: microVM overhead is material but bounded and preferable to unsandboxed autonomous build execution for risky tasks. Benchmark on B310 before making it default.
- Decision: ADAPT behind Captain as an optional builder execution backend after local capability/resource checks. Do not install automatically.

## New candidate: MCP Apps official extension
- Source: Model Context Protocol Core Maintainers announcement, checked 2026-09-12; production extension announced 2026-01-26.
- Capability: MCP tools can return interactive UI components such as dashboards, forms, visualizations and multi-step workflows directly to compatible clients.
- Integration fit: HIGH for Captain's low-friction interactive builder/settings/research panes, especially when a subsystem already exposes MCP. It can reduce bespoke UI glue while Captain remains the visible orchestrator.
- Isolation requirement: every rendered app/tool result still needs Captain's `chat_id + project_id + repo_scope + state_epoch` authority envelope; an MCP app must never become an independent memory/task control-plane.
- Security/dependencies: prefer official SDK/spec; deny arbitrary remote app origins by default, sanitize app metadata, and gate permissions through Captain Settings.
- Resource cost: likely low relative to a full embedded IDE; browser/webview cost still needs local profiling.
- Decision: PRIORITY ADAPT candidate for generic interactive subsystem UI; prototype only after the current epoch-bound builder/memory contracts are reconciled locally.

## New candidate: OpenHands Software Agent SDK
- Source: upstream OpenHands Software Agent SDK repository, checked 2026-09-12.
- Capability: Python/TypeScript/REST APIs for code agents, file editing, task tracking and ephemeral workspaces via an Agent Server.
- Integration fit: MEDIUM. Mature coding primitives may save implementation work, but the complete OpenHands agent/server architecture overlaps Captain's orchestrator and could accidentally create a second control-plane.
- Security/isolation: acceptable only as a narrowly scoped builder/tool adapter behind Captain; no direct ownership of cross-project memory, routing, connector auth or persistent jobs.
- Resource cost: local agent server/container execution can be material; benchmark before adoption.
- Decision: EVALUATE/ADAPT selective SDK primitives only. Do not install or run automatically; prefer Captain's existing OpenBuilder flow unless specific OpenHands primitives clearly outperform it.

## Existing candidate update: Freebuff / Codebuff SDK
- Source: current GitHub README checked 2026-09-12.
- Capability: Apache-2.0 Freebuff app, Codebuff multi-agent SDK/runtime, parallel local workspaces, browser/research agents, hosted sandboxes/previews.
- Data warning: hosted Freebuff services process prompts, traces, code/files/repository data and may expose model-specific training/data-use notices.
- Decision: continue to evaluate only the SDK/code-map/build-review pieces for local adaptation. Hosted repo processing stays opt-in and off by default.

## Community signal: per-project sandbox controls and lean harnesses
- Recent developer-community discussions continue to favor per-project filesystem mounts, network allowlists, credential isolation, resumable sessions and small/understandable coding harnesses.
- Reports also show local-model coding quality remains highly model/harness dependent, so Captain should keep routing/fallback quality separate from the builder harness itself.
- Treat community claims as leads only; verify candidates against upstream source/security docs before adoption.

## Implementation consequence for Captain
The continuity branches now contain provider-neutral safety primitives for sandbox/build/preview/settings plus an epoch-bound Project Memory/context envelope. The branch `automation/fallback-ci-20260912` additionally runs offline-safe fallback regressions automatically with least-privilege GitHub Actions; live HTTP/router tests remain explicitly deferred to the authorized laptop runtime.

Local reconciliation requirement: when the laptop is reachable, reconcile these changes first, run Doctor/router/OpenBuilder plus the live HTTP scope test, then benchmark any new subsystem before default-on use. No candidate above should be installed blindly or allowed to replace Captain's single control-plane.
