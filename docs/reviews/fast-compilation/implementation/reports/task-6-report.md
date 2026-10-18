# Task 6: compact bounded Wasm

Status: DONE_WITH_CONCERNS (backend complete; final Chromium/CSP integration belongs to coordinator).
Commit: a689c0e — Emit compact bounded Wasm with fresh correspondence and lexical locals.
Owned files committed: axiom/src/axiom/wasm.py, axiom/src/axiom/bounded_loop_wasm.py, axiom/tests/test_bounded_loop_wasm.py.

## Interface and implementation

`_compile_wasm_compact(owned, hint_bytes, *, hint_limits=HintLimits()) -> WasmArtifact` calls `_require_owned` and freshly validates the exact hint against the complete finite stream on every invocation. It consumes only the resulting program within that call. Trace phases: loop_correspondence, code_emission; counters: loop_correspondences, loop_correspondence_work.

Structured block/loop with break depth 1 and continue depth 0; lexical local allocator releases sibling scopes. Input preflight is an increasing loop preceding all stores. Index lowering retains constant/offset/parity/multiply/accumulate ordering; negative parity uses and 1. Fresh correspondence establishes every executed index intermediate fits i32; shared layout establishes byte scaling/address arithmetic fits one fixed page. Checked scalar operations remain in order, including dead operations. Scratch is neither assumed zero nor reset between calls.

WasmArtifact appends compatible default metadata: codegen_version, hint_digest, local_count, loop_version. Compact version is beryl-bounded-loop-wasm-v1; loop_version is CORRESPONDENCE_VERSION. Finite version is beryl-finite-wasm-v1. Public finite raw plan identity remains exact. Shared _layout/_module helpers extracted without changing finite module bytes.

## Tests and evidence

RED: `PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_wasm -q` — four intended failures: compact backend missing.
GREEN: same command — 4 tests, 17.321s.
Expanded GREEN: `PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_wasm tests.test_wasm -q` — 14 tests, 25.388s.
Additional maximum-depth check: `PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_wasm.CompactWasmTests.test_maximum_nested_label_depth_preserves_parent_locals -q` — 1 test, 0.053s.
`git diff --check -- axiom/src/axiom/wasm.py axiom/src/axiom/bounded_loop_wasm.py axiom/tests/test_bounded_loop_wasm.py` — clean.

Real Node/V8 validates and runs all three schedules at 1x1, 2x3, 5x7, 15x15, 1x127, 127x1. Each instance retains scratch across 21 changing valid/invalid calls. Complete 64KiB memory digests match finite Wasm; status/input/output also match independent source evaluation and the finite interpreter. Failures at first/middle/last input with signed extremes and multiple bad cells preserve every byte. Import-free ABI, exported names, fixed memory and rejected growth checked in engine. Negative index components/parity, signed literals, sibling reuse, zero-trip control, maximum 16-level nesting, quota/malformed/mismatching hints, expired/replaced ownership, overflow-before-cancellation covered.

Four deliberately broken emitters (continue target, scalar operand, index, output-store address) still produce valid modules; actual engine observations differ and tests detect all four. Module hash is not used as a correctness oracle.

A standalone comparison loaded wasm.py from ad9f136 and confirmed 18 finite modules (all schedules/six boundary shapes) remain byte-identical.

## Size and illustrative one-shot timing evidence

15x15, finite -> compact:
- inline-v1: 40,536 -> 404 bytes; 3,376 -> 18 locals.
- rows2-v1: 32,924 -> 765 bytes; 2,344 -> 10 locals.
- materialize-v1: 32,914 -> 481 bytes; 2,344 -> 10 locals.

One diagnostic sample per schedule, without sweeps; nanoseconds:

| Schedule | Python emission | Correspondence | JS compile | JS instantiate | First run |
|---|---:|---:|---:|---:|---:|
| inline | 138175 | 35858160 | 449658 | 88822 | 211484 |
| rows2 | 147589 | 27184566 | 273386 | 28773 | 46209 |
| materialize | 105046 | 26745733 | 109373 | 23435 | 30405 |

JS compile/instantiate/run measured separately with process.hrtime.bigint; Python code_emission phase excludes correspondence. Each first run returned 0. Concurrent environment and one-shot measurement preclude speed claims; native machine-code compilation may be lazy or engine-cached.

## Self-review and limitations

Reviewed local lifetime boundaries, nested branch labels, preflight return ordering, signed comparisons/parity, address bounds, exact source/plan/hint bindings, and legacy bytes. No larger shape or language feature admitted; no import/memory growth introduced. No unowned files changed or committed. Full production suite intentionally reserved for coordinator final integration. Chromium under shipped CSP not run here; coordinator explicitly schedules it. Independent review still pending.
