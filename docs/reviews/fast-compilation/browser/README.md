# Fresh-source browser compilation profiling

This scratch harness measures the current release implementation. It changes no repository or release files. The actual release `beryl-compiler.zip` is unpacked into Pyodide; wrappers time calls to its real `prepare_compiled_demo` pipeline. All 20 preparations succeeded and their emitted modules executed against an independent four-cell stencil formula.

Run with the existing server rooted at `/workspace/scratch` on port 38067:

```sh
node /workspace/scratch/beryl-compile-research/browser/profile.cjs > /workspace/scratch/beryl-compile-research/browser/run.log 2>&1
node /workspace/scratch/beryl-compile-research/browser/counts.cjs > /workspace/scratch/beryl-compile-research/browser/counts.log 2>&1
python /workspace/scratch/beryl-compile-research/browser/verify-inputs.py > /workspace/scratch/beryl-compile-research/browser/input-integrity.log
```

`phase-results.json` retains every sample, full nonce-bearing source, source digest, selected plan, module digest and phase timings. It also records browser, runtime, Python, host and exact input/harness file hashes. `call-counts.json` is an independent cProfile run, used only for call counts. `input-integrity.json` verifies that HTTP files equal local hashed inputs, the compiler ZIP/member hashes match the release manifest, and retained harness hashes match the scripts.

Measured environment: Chromium 154.0.8037.57, Pyodide 0.27.7, Python 3.12.7, Emscripten 3.1.58. Runtime startup plus compiler imports took 2,399.1 ms and is excluded from all compilation samples. The compiler ZIP SHA-256 is `cb7304afabbfee94c4184f1c34574732f0f241c2a674222d6c3a8ee014bb6634`; the pinned runtime Wasm SHA-256 is `a50dd1843f805a0b7c45b61037ee0d7b26dfe85efe0e18ef95a34ad24e401f5f`.

## Scope and limitations

One browser and Worker are used. There is no compilation warmup before the first 1x1 source. Each sample has a new fixed-length comment nonce and goes through the real fresh preparation path, including four semantic checks. Runtime/imports remain loaded. Cases rotate between samples; first samples occur in the listed case order, so their execution also advances engine/runtime warmup. They are first distinct source/module encounters for that browser, not independently cold runtime processes.

The harness calls `WebAssembly.compile` and `WebAssembly.instantiate` for every sample, retains no compiled module for reuse, and does not invoke the product Worker's source-reuse shortcut. Repeated same-case emitted module bytes are identical because source comments do not change generated instructions. V8 may reuse machine code internally on those repeated modules. Accordingly, first distinct module samples and repeated source-fresh samples are reported separately. No claim is made that repeated JS compile timings represent uncached machine-code generation.

Timings are observational on one shared host, with five samples per case, and include instrumentation overhead. Browser timing resolution produces some 0.0 ms readings for tiny operations. These are not zero-cost claims. First execution is validated afterward but is not separately timed; any engine-lazy compilation charged to first execution is therefore outside these phase measurements. There are no implementation speedup measurements here.

## First distinct module samples

Milliseconds, runtime/import startup excluded:

| Shape/cap | Selected | Initial admission | Selection | Fresh backend admission/decode/check | Wasm emission | Full Python prepare | Full Worker compile | JS compile | JS instantiate |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1x1 / 64 | inline | 2.6 | 13.1 | 5.4 | 1.4 | 22.8 | 25.5 | 0.2 | 0.0 |
| 5x7 / 64 | rows2 | 1.4 | 136.9 | 38.2 | 3.0 | 179.7 | 181.9 | 0.3 | 0.1 |
| 15x15 / 64 | inline | 1.2 | 312.5 | 258.1 | 17.0 | 589.3 | 595.1 | 0.4 | 0.0 |
| 15x15 / 128 | rows2 | 1.5 | 313.5 | 184.9 | 11.1 | 513.9 | 518.0 | 0.3 | 0.0 |

The four module digests are distinct; raw results retain their complete values.

## Five source-fresh samples per case

Full Worker compilation milliseconds, chronological within each case:

| Shape/cap | Samples | Median |
|---|---|---:|
| 1x1 / 64 | 25.5, 11.8, 12.4, 12.5, 13.1 | 12.5 |
| 5x7 / 64 | 181.9, 100.8, 88.5, 88.2, 89.4 | 89.4 |
| 15x15 / 64 | 595.1, 544.6, 555.2, 572.8, 558.5 | 558.5 |
| 15x15 / 128 | 518.0, 511.7, 502.3, 526.4, 517.9 | 517.9 |

Median phase times, milliseconds:

| Shape/cap | Initial admission | Selection | Fresh backend admission/decode/check | Wasm emission | Full Python prepare | Python bridge | Base64 decode | JS compile | JS instantiate | Full Worker compile |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1x1 / 64 | 1.0 | 6.7 | 2.9 | 0.1 | 11.5 | 12.1 | 0.0 | 0.2 | 0.0 | 12.5 |
| 5x7 / 64 | 1.0 | 52.8 | 32.0 | 1.9 | 88.2 | 88.7 | 0.4 | 0.3 | 0.1 | 89.4 |
| 15x15 / 64 | 1.1 | 290.3 | 248.6 | 13.9 | 552.9 | 555.8 | 2.6 | 0.3 | 0.1 | 558.5 |
| 15x15 / 128 | 1.1 | 313.5 | 184.9 | 10.5 | 513.9 | 515.3 | 2.0 | 0.3 | 0.0 | 517.9 |

Each column is an independent median, so median components need not add to median total.

## Phase definitions

- `initial_admission_ms`: production service's `_request_source`, initial `parse_source`, and initial `admit_source` calls.
- `selection_ms`: inclusive production `select_plan`, including candidate generation, all three checks, encoding and repeated admission.
- `fresh_check_ms`: inclusive backend `_checked_plan`, including fresh source parsing/admission, plan decoding/validation and the fourth semantic check.
- `wasm_emit_ms`: inclusive `compile_wasm` less its nested `_checked_plan`; includes body/module emission, artifact construction and related hashing. It is a measured residual, not isolated machine-code generation.
- `service_other_ms`: remaining Python preparation time, including reports, base64 encoding and retaining preparation state.
- `python_prepare_ms`: complete production `prepare_compiled_demo`, before serializing its result for JavaScript.
- `python_bridge_ms`: source transfer and `runPython` call, Python preparation, Python JSON serialization, and JS JSON parsing.
- `worker_compilation_total_ms`: full Worker wall time through source transfer, Python preparation/result serialization, base64 decoding, JS Wasm compilation and instantiation. Formula verification happens afterward and is excluded.

## Independent call counts

Every case invokes three generators, four semantic checks, seven source parses/admissions and one plan decode. Encoding/validation counts depend on how many selection candidates satisfy constraints:

| Shape/cap | Eligible selection candidates | `encode_plan` | `validate_plan` |
|---|---:|---:|---:|
| 1x1 / 64 | 3 | 7 | 8 |
| 5x7 / 64 | 2 | 6 | 7 |
| 15x15 / 64 | 1 | 5 | 6 |
| 15x15 / 128 | 2 | 6 | 7 |

## Architectural implication

The browser evidence supports the proposed order: first retain an internally owned freshly checked artifact through emission; then introduce a versioned candidate-ranking/check policy; then consider source/DAG sharing if a new profile warrants it. At 15x15, the repeated backend admission/decode/check occupies a large observed fraction of preparation. Initial source admission itself is small. JS compilation/instantiation is small in these samples, including each first distinct emitted module, so replacing the JS Wasm compiler is not supported by this evidence.

Keep the first milestone compatible with current selection order, deterministic work budgets, public byte APIs, forged-record rejection and exact artifact identities. Ranked-first semantics need a separate policy contract for unknown/budget/cancellation cases. DAG sharing should follow because it adds accounting and quota obligations after the first two milestones have already removed most repeated proof construction.
