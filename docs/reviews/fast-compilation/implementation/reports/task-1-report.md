# Task 1 report

Status: DONE. No production compiler behavior, public archive allowlist, work receipts, quotas, selection rules or release flags changed by these files. Full production/integration qualification remains the coordinator's final step.

## Delivered interface and files

- `axiom/src/axiom/compilation_trace.py`: optional request-local `CompilationTrace(*, clock=perf_counter_ns)`, `.phase(name)`, `.count(name, amount=1)`, `.report()`. Schema v1: `timing_unit: ns`, `timing_semantics: inclusive`, `phases[name] = {elapsed_ns,calls}`, integer `counts`. Snapshots are detached, exception exits close timers, exact nonnegative integers required for count amounts. Callers branch on `trace is not None`; this module introduces no disabled-path call, monkeypatch or global collector. Nested timings overlap. `PHASES` documents the requested canonical names; custom names permit additive subphases.
- `tools/profile-compilation.py`: isolated baseline/candidate checkout subprocesses, rotating revision order, raw uninstrumented preparation samples, separate optional first-round cProfile/request-local trace diagnostic preparations, module local-declaration reader, exact source/module/plan metadata and compiler/module/harness hashes. Optional Clang native compilation, separate trace/object/optimized-IR builds and external output audit. Native scope explicitly retains legacy public selection plus fresh public byte emission, rather than claiming to measure the owned browser service transaction.
- Boundary fixtures include seven required/boundary/parity shapes, both objectives, below/equal/above each schedule reservation, source-only comment/rename, cap/objective and input-only edit fixtures. Full literal sources available through `--list-fixtures`; exact filtering through `--fixture-id`.
- `tools/benchmarks/compilation.cjs`, `compilation-worker.js`, `compilation-wasm.js`: research-only local server plus Chromium harness. Default 21 independently engine-cold samples, each with a new process, temporary profile and Worker; runtime/import boot precedes the first user program and is retained separately. Alternative source-fresh mode explicitly discloses engine cache reuse on identical emitted modules. Paired sites share source bytes/nonces and alternate order. Complete first and changed-input observations are audited by retained original AST and an external formula. No user-program warmup. Separate prepare, compile, instantiate, first execution and verification; optional diagnostics run afterward. Exact browser command line/V8 identity, local/served compiler/runtime/harness file hashes and raw observations are retained.
- `tools/compare-playground.py`: original execution sample scope and compilation fields preserved; additive C/plan/operation/executable sizes, flags and native compile phase/scope labels.
- `axiom/docs/playground.md`, `tools/benchmarks/compilation.md`: schema, exact scopes, portable commands, fixture matrix and limitations.
- Python and Node contract tests assert identities/counts/boundaries rather than millisecond thresholds.

## RED evidence

`cd axiom && PYTHONPATH=src python -m unittest tests.test_compilation_trace -v`

Observed six expected missing-feature errors before implementation: missing `axiom.compilation_trace` and missing `tools/profile-compilation.py`. A preliminary invocation used an incorrect relative output path and was corrected before the feature RED run.

`cd axiom && PYTHONPATH=src python -m unittest tests.test_compilation_trace.NativeCompilationFieldTests -v`

Observed missing `binary_bytes` field before extending native compilation records.

`node tools/benchmarks/test-compilation.cjs`

Observed missing `compilation.cjs` before implementing the browser contract helpers.

## Final targeted GREEN evidence

From `axiom/`:

```sh
PYTHONPATH=src AXIOM_TEST_NATIVE_CLANG=/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang python -m unittest tests.test_compilation_trace tests.test_playground_benchmark -v
```

Result: 18 tests passed, no skips, including an actual emitted native executable with different runtime inputs.

From repository root:

```sh
node tools/benchmarks/test-compilation.cjs
node --check tools/benchmarks/compilation.cjs
node --check tools/benchmarks/compilation-worker.js
node --check tools/benchmarks/compilation-wasm.js
python3 -m py_compile tools/profile-compilation.py tools/compare-playground.py axiom/src/axiom/compilation_trace.py
git diff --check -- tools/compare-playground.py axiom/docs/playground.md
```

Results: Node contract assertions passed; all syntax/whitespace commands exited zero. Full production suite is intentionally left for the coordinator's single final integration run per task brief.

## Functional smoke commands and retained raw outputs

```sh
python3 tools/profile-compilation.py --fixture-set smoke --samples 1 --diagnostics --output /tmp/beryl-compilation-python-smoke.json
python3 tools/profile-compilation.py --fixture-set smoke --samples 1 --diagnostics --cc /workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang --output /tmp/beryl-compilation-native-smoke.json
python3 tools/profile-compilation.py --fixture-set smoke --samples 2 --baseline-repo /workspace/BerylLattice-o3-fixes --output /tmp/beryl-compilation-python-self-pair.json
node tools/benchmarks/compilation.cjs --site /workspace/scratch/beryl-compiled/site-release --baseline-site /workspace/scratch/beryl-compiled/site-release --mode source-fresh --fixture-set smoke --samples 2 --diagnostics --output /tmp/beryl-compilation-browser-self-pair.json
node tools/benchmarks/compilation.cjs --site /workspace/scratch/beryl-compiled/site-release --fixture-set smoke --samples 1 --diagnostics --output /tmp/beryl-compilation-browser-final-smoke-v2.json
```

All exited zero. Self-pairs intentionally use the same checkout/site to test pairing/order/identity mechanics; they are not speedup evidence. Python wall samples excluded cProfile/trace runs. Native diagnostic smoke produced independently audited inline C, real compiler/link, object and optimized IR, and retained Clang time-trace events.

The final cold-browser baseline smoke reproduced the retained 1x1-cap64 baseline exactly: module 267 bytes, 16 declared locals; source parse/admit 7 each, semantic `check_plan` calls 4, generators 3, internal decode 1, encode 7, structural validate 8. Both first and changed-input complete observations matched original AST and independent formula. Temporary report checks additionally verified pairing order reversal, identical source/module identities within self-pairs, cold browser/profile flags, actual command line, phase presence and served-file audit. Actual new optimized release counts/bytes must be collected after the coordinator builds it.

An intermediate final cold smoke failed on CDP `Browser.getBrowserCommandLine` because this managed Chromium did not enable automation by default. The launch now passes explicit `--enable-automation`, permitting exact command-line retention. The final `-v2` smoke passed. Browser boot failure cleanup closes the process/removes its temporary profile.

## Limitations and self-review

- No 21-sample qualification or large timing matrix was run in parallel with implementation; this is deliberate per coordinator instruction. No wall-time speedup claim is made.
- Python-only Wasm preparation does not execute modules; the browser harness supplies independent observation audits. Python native compilation has its separate explicit legacy-public scope.
- Browser phase clocks are milliseconds and may round tiny operations to zero. Timings are inclusive. `python_prepare_bridge` includes Python preparation plus serialization/bridge; request-local diagnostic trace narrows compiler phases separately.
- Worker runtime boot and browser-launch-plus-boot have separate fields. The interpreter-only Python boot field explicitly covers compiler imports and excludes interpreter process startup.
- Actual fetched runtime files and archive bytes are independently audited; full release archive-member/manifest validation remains the static builder's existing responsibility.
- Portable browser dependencies are configurable. The default managed installation path is a fallback after normal `playwright-core` resolution; self-hosted runtime is required for local served-file audits.
- Public archive allowlist intentionally unchanged. Coordinator must include the bounded trace module when the newly built service import closure requires it.
- Reviewed ownership: only assigned instrumentation/tests/tooling/docs plus this requested report changed. Other agents' compiler files were read but never edited.

Commit: `de89b44` — Add request-local compilation traces and paired research profiling harnesses.

## Follow-on: source-native profiler integration

Status: DONE. This section supersedes the earlier limitation that native profiling always uses the legacy public pipeline. Only `tools/profile-compilation.py`, its focused `axiom/tests/test_compilation_trace.py`, and `tools/benchmarks/compilation.md` changed in this follow-on; `compare-playground.py` and compiler modules were not edited.

The native profiler now resolves the selected checkout's actual `compile_native_source` API before timing runtime-ready work. Candidate source-coordinator samples freshly admit/rank/prove and emit compact C or typed finite fallback. Older checkouts with no source coordinator/API use the original public admission/selection/fresh-byte-emission pipeline. Missing dependencies inside a present source coordinator propagate instead of silently choosing the baseline path. Worker boot includes native imports when `--cc` is requested.

Native measurement schema version 2 records `pipeline`, full `source_compilation_seconds`/`source_compilation_ns`, separate actual compiler/link duration, and `total_fresh_native_preparation_seconds`/`_ns`. The total is a continuous wall interval from fresh source preparation through C-file materialization and real compiler/link. It is not a sum of selected phases. Hashing, independent native execution audits, optional native cProfile/trace preparations and optional compiler trace/object/IR builds happen afterward. No old selection/emission subdivisions are fabricated for the new coordinator. Every sample records actual source/plan/C/codegen/hint/policy identities, candidate states, deterministic checker work, flags and executable identity; `native_medians_ns` summarizes source/compiler/full-wall medians.

Extracted snapshots now retain `kind: source-snapshot`, null Git revision/dirty state, separately declared origin revision from `--baseline-revision`/`--repo-revision`, and exact module hashes. The tool never inherits a surrounding checkout's HEAD. Caller-declared origin is explicitly not a verified Git identity. The actual baseline snapshot used for the smoke below was separately checked against every `git show 39dc2f6:<module>` blob hash.

### RED

```sh
cd axiom
PYTHONPATH=src AXIOM_TEST_NATIVE_CLANG=/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang python -m unittest tests.test_compilation_trace.NativeSourceProfilerTests -v
```

Before implementation: three expected missing-feature errors (`native_pipeline` absent and incompatible old timing call layout); the already-supported CLI no-overwrite/listing contract passed. The initial compact-size assertion used an arbitrary 10,000-byte limit; actual compact 15x15 C is 11,579 bytes. The assertion was corrected to the approved >=10x reduction against real finite C (200,517 bytes), rather than imposing a new size requirement.

```sh
PYTHONPATH=src python -m unittest tests.test_compilation_trace.NativeSourceProfilerTests.test_archive_provenance_keeps_declared_revision_distinct_from_git_identity -v
```

Before snapshot support: expected unsupported `declared_revision` argument error.

### Final GREEN and actual paired smoke

```sh
cd axiom
PYTHONPATH=src AXIOM_TEST_NATIVE_CLANG=/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang python -m unittest tests.test_compilation_trace -v
```

Result: all 13 focused tests passed, no skips. Coverage includes real compact 15x15 artifact/codegen/hint identities, >10x actual source-size reduction, old-API feature detection with real legacy generation, no silent fallback on nested dependency failure, real small-shape Clang executable/output audit, deterministic injected-clock interval coverage including file-write gap, separate native trace/cProfile diagnostics, snapshot identities, and preserved fixture/trace/CLI/no-overwrite contracts.

From repository root:

```sh
python3 tools/profile-compilation.py --repo /workspace/BerylLattice-o3-fixes --baseline-repo /workspace/scratch/beryl-fast-compilation/baseline --baseline-revision 39dc2f6 --fixture-set smoke --samples 1 --diagnostics --cc /workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang --output /tmp/beryl-source-native-paired-final-smoke.json
python3 -m py_compile tools/profile-compilation.py
git diff --check -- tools/profile-compilation.py axiom/tests/test_compilation_trace.py tools/benchmarks/compilation.md
```

All exited zero. The actual paired 1x1 smoke uses the candidate source coordinator and archived old manual public pipeline, with identical source/plan identities and two independently audited real native executables. Both full-wall scopes and separate trace/cProfile/object/IR/compiler-trace evidence are retained. Baseline trace support remains null; its cProfile call counts are retained. Independent assertions also checked full-wall >= source + compiler intervals, native medians, compiler object evidence, declared baseline provenance and exact archived module hashes against Git39dc2f6. This one-sample smoke verifies operation and identity only; it is not a performance qualification or speedup claim.

An attempted earlier baseline path `/workspace/BerylLattice` lacked the playground service and was not used for measurement. The coordinator supplied the actual archived baseline path above. No worktree or branch was created. Full production suite and serial 21-sample qualification remain the coordinator's integration step.

Self-review: compiler/frontend/link work remains fresh and fully timed on both paths; the source coordinator's actual returned C is what Clang compiles; no service/Wasm proof is reused in native generation. Diagnostic work does not enter wall samples. New archive provenance never claims a false clean Git checkout. Only assigned follow-on files changed.

Follow-on commit: `21f36d4` — Profile actual source-native coordinator against archived legacy baselines.
