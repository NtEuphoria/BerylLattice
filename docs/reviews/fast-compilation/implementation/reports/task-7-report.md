# Task 7 integration report

Status: DONE (integration scope; release qualification and publication remain controller-owned).

Commit: `4e54e98` — Integrate fresh ranked source compilation into bounded playground release.

## Implementation

- Added `source_compilation.compile_native_source` / `compile_wasm_source` returning frozen `SourceCompilation(kernel, search, artifact, hint_failure)`. Every call owns a fresh context, ranked selection and emission; closes in `finally`, including cancellation. Only typed `HintError` / `DecodeError` triggers finite emission; arbitrary emitter faults propagate. Hint intent uses the successful portfolio attempt identity, independently of arbitrary plan labels. Exact fresh backend correspondence remains decisive.
- Compiled service uses this coordinator once and retains immutable original AST/search/artifact only. Every preparation clears stale state before work. Schema 2 exposes ranked policy/version/digest, optimality, actual skipped structural metrics, nullable eligibility and lowering identity. Legacy interpreter remains schema 1. Every observed request still performs original-AST comparison and exact scalar validation.
- Browser uses backend `checked-plan-wasm-v2`, accepts only schemas 1/2, distinguishes lower-priority unproved candidates and budget-limited no-selection, preserves original compilation cost after reuse. Updated benchmark guard to accept the new report; transport cancellation protocol unchanged.
- Explicit bounded public allowlist now 22 modules: prior 13 plus compilation, compilation_selection, source_compilation, bounded_loop_model/codec/planner/correspondence/c/wasm. MIT/branding/hash/import-closure tests retained. No tracing tool, scalable v2, Core binding, research or session source exported.
- Native comparison loader optionally discovers source API, verifies archive origin, uses fresh source helper when present, and falls back to legacy pipeline only when the module is absent. Combined `source_compilation_seconds` is distinct; legacy phase fields are null in source-API mode. Existing process scope preserved. README/docs describe implementation without performance qualification claims.

## RED / GREEN evidence

- New source tests initially failed 4 assertions: coordinator missing. Implemented and green. Relabelled valid plan exposed `ValueError: unsupported bounded schedule`; changed intent lookup to successful attempt identity and green.
- Service schema test failed `1 != 2`; now schema2, exact skipped costs, null unproved eligibility and real compact metadata pass.
- UI schema2 test failed because result was unrecognized; now costs and honest states render. Unknown budget test failed `No plan fits these constraints`; now `No plan selected`.
- Public package test failed on nine absent allowlisted modules; package/import closure now passes.
- Native comparison test failed missing `search_policy`; new source timing/artifact metadata and real Clang changing-input execution now pass.
- Real Chromium discovered benchmark table rejecting v2 backend with `Correctness check failed`; guard corrected. Final expanded browser smoke passes. One added browser assertion initially expected `0` instead of existing visible `0 B`; corrected assertion, no product behavior change.

## Verification

From repository root:

```
PYTHONPATH=axiom/src:axiom AXIOM_TEST_NATIVE_CLANG=/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang python -m unittest tests.test_source_compilation tests.test_compilation tests.test_playground_service tests.test_playground_site tests.test_playground_benchmark -q
```

66 tests PASS, 4.623 seconds. Includes real Clang generated executable on changing inputs, finite fallback capability, source context lifetime, cancellation, arbitrary relabel and unmatched dead operation fallback, actual compact Wasm ZIP execution with changing input and first/final invalid preflight, report tampering, state invalidation, exact hashes, MIT, branding and complete import closure.

`node tools/test-playground-ui.cjs`: 17 tests PASS. Includes cancellation/reset races, original compilation cost on reuse, schema2 candidate display, unknown schema and unproved selection wording.

```
python tools/build-playground-site.py --output /workspace/scratch/beryl-fast-compilation/integration-site-v2 --runtime-cache /workspace/scratch/beryl-compiled/site-release/runtime
PLAYWRIGHT_MODULE=/opt/codex/cua_node/lib/node_modules/playwright-core CHROMIUM_PATH=/usr/bin/chromium node tools/check-playground-browser.cjs http://127.0.0.1:38067/beryl-fast-compilation/integration-site-v2/
```

Vendored 24-file build PASS; runtime assets hash verified. Actual Chromium PASS: cold rows2, download schema/policy/hashes, cap/objective changes, reused source, initial cost retained, 256-input final invalid position with 225 sentinels preserved, actual worker cancellation/restart, unsupported source, reset, responsive widths, keyboard, saved native table and actual compiled browser benchmark table, no page errors. Evidence `/workspace/scratch/beryl-fast-compilation/integration-browser-final.txt`.

`git diff --check`: PASS.

## Self-review / limitations

- No full production suite, timing qualification, benchmark-results refresh or publication performed; these belong to controller. Browser numbers are smoke observations, not qualification. Existing valid release unchanged.
- Trace `plan_validations=3` counts only candidate-phase work, not additional correspondence validation passes. Docs explicitly qualify this; source wall time includes all work.
- Old archive fallback is tested as absent capability using real legacy compiler; final exact old/public archive timing run remains controller-owned.
- Browser site candidate was built before final docs-only changes; controller must rebuild for final release, as expected. No private context/proof is accepted by source APIs, and no retained live context authorizes later runs.

## Follow-up: standalone optional trace collector

Commit `13ed86c` adds the independently reviewed, standard-library-only `compilation_trace` collector to the explicit bounded public allowlist (now **23 modules**). The generated license scope counts modules dynamically; standalone test count and developer docs now agree. This corrects the earlier exclusion of the collector: only research measurement harnesses remain private, while the advertised optional `trace=` API is usable from the standalone ZIP.

RED: new standalone trace regression reproduced `ModuleNotFoundError: No module named 'beryl.compilation_trace'` against the actual generated ZIP. GREEN: `PYTHONPATH=axiom/src:axiom python -m unittest tests.test_playground_site -v` — **10 tests PASS**, 2.570 seconds. Coverage imports the collector under isolated Python with only the ZIP, verifies traced and untraced preparation are identical, verifies candidate-phase/semantic/correspondence/emission counts, independently mutable diagnostic snapshots, forged trace request rejection, invalid-source rejection and stale-preparation invalidation. Existing MIT/branding/import closure/hash and real Wasm ZIP execution checks pass.

Rebuilt hash-verified vendored candidate at `/workspace/scratch/beryl-fast-compilation/integration-site-trace` (24 site files, 23 compiler modules). `git diff --check` PASS. No UI code changed; UI rerun unnecessary. Controller will rerun actual research-browser diagnostic and schedule scoped review.
