# Captain OSS Scout — 2026-09-12

Daily scan focus: safe builder execution, project isolation, and reusable coding subsystems.

## Priority candidate: Docker Sandboxes (`sbx`)
- Source: official Docker documentation, checked 2026-09-12.
- Capability: isolated microVM per coding-agent sandbox, dedicated filesystem/network/Docker daemon, project workspace sharing, credential proxying, network policy, supported agents including Codex/Claude/Gemini/OpenCode.
- Windows fit: official docs list Windows 11 + Windows Hypervisor Platform; Docker Desktop is not required for `sbx`.
- Control-plane fit: strong if Captain owns sandbox lifecycle and passes only a scoped project workspace; do not allow `sbx` or an underlying agent to become a second router/orchestrator.
- Security fit: prefer clone/read-only workspace mode where possible; network deny by default; credentials through host-side proxy/official OAuth only; never inject raw secrets into agent prompts or files.
- Resource cost: microVM overhead is material but bounded and preferable to unsandboxed autonomous build execution for risky tasks. Benchmark on B310 before making it default.
- Decision: ADAPT behind Captain as an optional builder execution backend after local capability/resource checks. Do not install automatically.

## Existing candidate update: Freebuff / Codebuff SDK
- Source: current GitHub README checked 2026-09-12.
- Capability: Apache-2.0 Freebuff app, Codebuff multi-agent SDK/runtime, parallel local workspaces, browser/research agents, hosted sandboxes/previews.
- Data warning: hosted Freebuff services process prompts, traces, code/files/repository data and may expose model-specific training/data-use notices.
- Decision: continue to evaluate only the SDK/code-map/build-review pieces for local adaptation. Hosted repo processing stays opt-in and off by default.

## Community signal: per-project sandbox controls
- Recent developer-community reports continue to converge on per-project filesystem mounts, network allowlists, credential isolation and resumable sessions as the useful baseline for coding agents.
- Treat community claims as leads only; verify any candidate against upstream source/security docs before adoption.

## Implementation consequence for Captain
The fallback branch `automation/sandbox-session-policy-20260912` adds a provider-neutral SandboxLease policy with:
- exact `chat_id + project_id + repo_scope + state_epoch` binding;
- stale-epoch/cross-project denial;
- safe defaults: clone workspace, network deny, credential proxy;
- raw-secret rejection;
- backend allowlisting so arbitrary daemons cannot silently become execution backends.

Local reconciliation requirement: on B310, inspect `sbx` system compatibility only after explicit integration review; do not install blindly. First reconcile and run the policy regressions, then Doctor/router/OpenBuilder regressions, then benchmark idle/RAM/startup cost before any default-on decision.
