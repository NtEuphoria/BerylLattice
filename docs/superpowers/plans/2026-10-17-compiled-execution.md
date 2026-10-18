# Compiled execution implementation

Design: `docs/superpowers/specs/2026-10-17-compiled-execution-design.md`.
Execution uses independent backend agents and a coordinator for the shared
compilation boundary, browser integration and release.

1. Refactor `runtime.py` to extract `_checked_plan` without changing execution
   behavior. Existing runtime/checker tests establish boundary compatibility.
2. Add `native_codegen.py` and `test_native_codegen.py`: immutable C artifact,
   direct seven-op lowering, complete preflight, safe standalone input driver.
   Test emitted native programs and callable kernels with explicit Clang.
3. Add `wasm.py` and `test_wasm.py`: direct bounded binary module emission,
   disjoint owned memory, SSA locals, preflight and deterministic artifact identity.
   Execute real modules in Node and compare complete source observations.
4. Extend `playground_service.py` with source preparation and independently checked
   completion APIs; keep `run_demo` as the existing full reference path. Add service
   tests for input boundaries, changed inputs, source identity and disagreement.
5. Extend Worker/transport for owned preparation and compiled execution. Keep reset,
   cancellation, error recovery and report downloads. Show compile and execution
   times separately. Add UI boundary tests and real-browser execution checks.
6. Extend `compare-playground.py` to precompile beryl before native timing and retain
   old Python scope as an explicitly named optional measurement. Record hashes,
   flags, selected plan, compilation costs, samples and external formula audits.
   Obtain an isolated Rust compiler if absent and verify its official checksums.
7. Update browser performance measurements to prepare once, execute varying inputs,
   and audit every result. Export reviewed `wasm.py` explicitly; update the exact
   archive allowlist and standalone public execution tests.
8. Review backend trust boundaries, memory/alias/overflow behavior, benchmark scopes
   and source export independently. Run full tests once final behavior is stable.
9. Measure C/Rust/beryl serially on the same host, retain reproducible evidence and
   publish the bounded package after validating all manifest hashes. Verify the
   hosted bytes and real-browser execution. Create and attach the private PR.
