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

## Decision
Neither candidate is installed. Agor is currently the stronger UX/branch-session reference; AIO Sandbox is the stronger compact runtime-adapter candidate. Captain remains the authoritative user-facing orchestrator and source of project/session truth.
