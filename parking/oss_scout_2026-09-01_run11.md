# Captain OSS scout addendum — 2026-09-01

No third-party code was installed or executed. This addendum records only newly surfaced candidates/changes from the current scan.

## Harbor / Terminal-Bench evaluation harness
- Capability: open-source framework for running agent evaluations in containerized environments, including Terminal-Bench and other coding-agent datasets.
- License: Apache-2.0 is reported by the current upstream repository.
- Fit: high as an external/equivalent acceptance harness for Captain's repo-aware build/debug loop; it should remain an evaluation subsystem, never Captain's router or persistent memory authority.
- Resource cost: potentially high on the user's laptop because Docker/container workloads and benchmark suites are heavy. Start only with a tiny deterministic smoke subset after reconnect and profiling.
- Paid-service note: Harbor can use cloud sandboxes/models, but Captain must not activate or consume those automatically. Prefer local/free existing providers and explicit Settings permission for any paid provider.
- Decision: prioritize a narrow adapter/eval contract; no installation until local Docker/resource/security compatibility is checked.
- Source: https://github.com/harbor-framework/harbor

## boldblackai/harness
- Capability: container wrapper around multiple coding agents with capability-dropped Docker execution, `no-new-privileges`, narrow mounted-path visibility, signed images/SLSA provenance and local-first model support.
- Fit: medium-high as sandbox/security reference for builder-session execution and repo-scope walls; whole-agent adoption would duplicate Captain's orchestration surface.
- Security value: its narrow mount boundary and supply-chain verification are directly relevant to Captain's fail-closed repo isolation.
- Resource cost: Docker plus agent/model runtime; likely moderate-to-high on the laptop and needs profiling.
- Decision: audit its sandbox flags, mount policy and provenance verification as reusable patterns. Do not install or run it yet.
- Source: https://github.com/boldblackai/harness

## BoundaryBench
- Capability: evaluates coding agents under progressively hardened sandbox policies derived from enterprise/NIST controls and uses Harbor-compatible evaluation artifacts.
- Fit: medium as a security-regression reference, not as a runtime subsystem. Useful for defining Captain's own capability-loss/security tradeoff tests.
- Resource/paid note: published runs use external sandbox/model providers; do not reproduce them automatically or incur cost. Reuse policy/test concepts locally where possible.
- Decision: mine policy scenarios into deterministic local adversarial tests after source review; no service activation.
- Source: https://github.com/boundary-bench/boundary-bench

## Priority change from this addendum
1. Keep connector health replay/persistence hardening first until the local Settings lifecycle is reconciled.
2. Add a small local deterministic Captain acceptance harness patterned after Harbor before considering broad benchmark runs.
3. Reuse narrow-mount/no-new-privileges/provenance ideas from boldblackai/harness for builder-session sandbox design.
4. Use BoundaryBench policies as adversarial regression inputs, not as a second control-plane or automatic paid benchmark pipeline.
