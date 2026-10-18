# Task 7 independent integration review

Verdict: **PASS** for integration specification and code quality. No material findings.

Reviewed commit `4e54e9878690fe84d694ca613e0e0b1642d319d8` against `task-7-brief.md`, using immutable `task-7-review-package.txt` (SHA-256 `8d4c1a1b280802e520e9e8e6ca32e718e1f180450fc7ef0f2e2a335434d1925c`). Context, ranked selection and compact backend contracts were treated as separately reviewed dependencies. Current integration files were checked against the pinned commit; no intervening changes were present in those files.

- Fresh source APIs accept no caller proof/context authority, preserve exact source identity, and close their context in `finally` on success, no-selection, failure and cancellation. Hint intent comes from the actual owned check's attempt identity, not a mutable plan label. Only typed hint/decode failures invoke finite fallback; unrelated emitter faults propagate.
- Preparation clears old state before work and installs only the completed result. Retained immutable original AST and exact source bytes govern subsequent observations. Every accepted observation receives independent AST evaluation; scalar validation precedes typed-array writes. No new request authority fields were added.
- Compiled schema 2 distinguishes structural costs, proof states and nullable unproved eligibility; legacy schema 1 and selection remain unchanged. Worker reuse retains the original compilation cost, while transport termination and stale-message rejection retain cancellation/reset behavior. CSP was not weakened.
- The explicit 22-module bounded export, MIT notices, branding guards, per-file hashes and standalone import closure cover the new dependencies without scalable v2, Core, research or recovery/session modules. Standalone tests exercise compact Wasm, changing inputs, boundary preservation and report/state tampering.
- Native comparison selects the source API only when available, includes it in archive-origin verification, preserves legacy capability fallback, and reports combined source time without inventing legacy subphase timings. Source/plan/C hashes are verified. Changing native inputs and external direct-formula audits remain outside measured execution intervals.

Evidence reviewed: implementation report's 66 focused Python tests and 17 UI tests; corresponding regression assertions; vendored-site/browser evidence at `/workspace/scratch/beryl-fast-compilation/integration-browser-final.txt`, which records actual Chromium cold/reused execution, final invalid input at the 256-input boundary, worker cancellation/recovery and benchmark checks. No suites or browser runs were repeated; static review found no unresolved issue requiring a targeted rerun.

This verdict does **not** qualify the release's latency/throughput targets or authorize publication. Final complete-suite execution, serial baseline/candidate measurements, exact final-archive checks, clean final provenance and release gates remain controller-owned as assigned.

## Follow-on: optional trace export

Verdict: **PASS**, no material findings. Reviewed scoped `4e54e98..13ed86c5a9ce8877e6787d1d232e29b52e16d5ab` package `task-7-trace-review-package.txt` (SHA-256 `319d51180f43aa16b3196522736e909d6577cdb5aa5ff3b868ae5ffcf19d0a6b`).

The sole export addition is the already reviewed `compilation_trace` collector, which imports only standard-library timing/context-manager support, stores diagnostic counters/times, and returns independent snapshots. It introduces no private dependencies, proof authority, network/filesystem access, or request fields. The explicit allowlist is now 23 modules; dynamic license scope and documentation agree. Existing branding rejection, exact archive membership/hash checks and import-closure tests continue to apply to every module.

The added isolated-ZIP regression checks importability, traced/untraced report identity, meaningful event counts, snapshot independence, forged trace-field rejection and stale-state invalidation after failure. Reviewed reported RED/GREEN evidence (10 package tests PASS) without repeating suites. Inspected the generated ZIP: exactly 23 Python modules, the collector identical to reviewed source, no private codename in it, and the standalone LICENSE present. `browser-diagnostic-trace.json` records a passed actual-browser retry against `integration-site-trace`; its single diagnostic sample is not release performance qualification. Earlier release-gate limitations remain unchanged.
