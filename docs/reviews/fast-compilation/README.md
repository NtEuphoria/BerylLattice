# Compilation latency research and baseline evidence

This is a measured diagnosis and reviewed implementation proposal, **not an implemented compiler speedup**. Research/profiling occurred on 2026-10-18 UTC against private baseline `39dc2f6df136c643cfd030ce4470503e807750fe` and the exact previously released bounded public compiler ZIP. No production compiler or public release files changed.

Start with the [architecture](../../superpowers/specs/2026-10-17-fast-compilation-design.md), [file-level plan](../../superpowers/plans/2026-10-17-fast-compilation.md), or [verified primary-source notes](research.md).

## Findings

1. Browser preparation spends most time in selection and repeated backend admission/decode/check, not the small initial parse or measured JS Wasm compile call. At 15×15/cap64, median full preparation was 558.5 ms; selection 290.3 ms, repeated backend boundary 248.6 ms and Wasm emission 13.9 ms. These are independent component medians and need not sum to total. First distinct module preparation was 595.1 ms.
2. Current preparation performs four semantic checks and seven source admissions. Plan encode/validation counts vary with eligible candidates. At 15×15/cap64, the counts are five encodes, six structural validations and one decode. An internally owned successful check can remove the decode/fourth check; a separate ranked policy can avoid proving worse candidates.
3. Native 15×15 inline code is 302,336 C bytes for 3,601 primitive operations. Fresh flag experiments gave median Clang times 363.6/381.9/399.9 ms at O1/O2/O3. The 9% O1 reduction from O3 is insufficient for the stated goal, and actual kernel throughput was not qualified. No optimization-policy change is justified yet.
4. Compact structured emission is the next backend experiment. It must retain exact finite-plan expansion correspondence, all numeric/storage/failure semantics and arbitrary valid finite fallback. It does not establish scalable v2 proof. The independent v2 gate remains blocked.

## Retained files

| File | Contents |
| --- | --- |
| `profile_compile.py` | CPython/current-private-compiler and generated-C probe, without production edits |
| `profile.json` | Seven unprofiled preparation samples per case; separate cProfile functions/call counts; five rotating flag samples per native plan |
| `provenance.json` | Baseline source-module hashes, compiler hash/config and host identity |
| `15x15-cap0-trace.json`, `15x15-cap128-trace.json` | Clang O3 compiler-only traces; nested categories are not additive |
| `browser/README.md` | Browser scope, raw phase interpretation, counts and limitations |
| `browser/phase-results.json` | All twenty preparations, exact nonce-bearing source, module/plan identities and phase samples |
| `browser/call-counts.json` | Independent cProfile call counts, not speed measurements |
| `browser/input-integrity.json` | Exact HTTP/local/ZIP/member/harness integrity checks |
| `browser/*.cjs`, `browser/*worker.js`, `browser/index.html`, `browser/verify-inputs.py` | Original unchanged scripts used for the retained browser observations |
| `research.md`, `research-sources.json` | Seven primary citations, applications/limits, access timestamps/URLs and downloaded-byte hashes |
| `review.md` | Independent review findings, resolutions and final checks |

Generated executables, C and object files remain under `/workspace/scratch/beryl-compile-research/profile`; their measured source hashes/sizes and derivation are retained. Source PDFs/HTML/text extractions remain in the scratch `literature` directory, not vendored into the repository. The access manifest records original downloads and failed URL attempts, not permanent availability or endorsement. A locally converted PCC PDF is a derivative of the separately hashed downloaded PostScript.

## Reproduction

Use the measured baseline compiler revision for byte/count reproduction. On a later implementation, the probe measures that implementation instead. No package installation is required for the CPython probe; the configured Clang path must be supplied.

```sh
python3 docs/reviews/fast-compilation/profile_compile.py \
  --repo /workspace/BerylLattice-o3-fixes \
  --output /tmp/beryl-compile-profile-new \
  --clang /workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang
```

The script loads imports once, makes one initial preparation before seven measured fresh preparations, then profiles separately. `prepare_compiled_demo` clears/rebuilds even for identical sources; this Python entry point does not use the Worker's reuse shortcut. Native flag samples compile/link the actual emitted plan and audit one ramp result per build. Clang trace data uses `-c`, excluding link. Timing variation and instrument overhead make these diagnostic baselines, not speedup qualification.

The browser scripts intentionally retain original paths/port to preserve their recorded hashes. To reproduce in this cloud setup, stage these unchanged scripts under `/workspace/scratch/beryl-compile-research/browser`, serve `/workspace/scratch` on port 38067, and provide the reviewed site at `/workspace/scratch/beryl-compiled/site-release`. The site ZIP hash must be `cb7304afabbfee94c4184f1c34574732f0f241c2a674222d6c3a8ee014bb6634` for exact retained-input identity. Pinned runtime files are local, and Playwright uses the environment's existing `/opt/codex/cua_node/lib/node_modules/playwright-core` plus `/usr/bin/chromium`. See the browser README for commands. On another environment adapt paths explicitly and record new harness/input hashes; that is a new observation, not the original measurement.

## Interpretation limits

Measurements are observational on a shared Linux host, not paired baseline/candidate improvements. CPython 3.12.14/private-source preparation and Chromium/Pyodide 0.27.7/Python 3.12.7/public-archive preparation are separate scopes. Do not compare their times as implementation speedups or compare them with a different user's device. The earlier [native comparison](../compiled-execution/README.md) supplies C/Rust reference build costs; these new probes did not rerun a matched C/Rust build comparison.

The browser harness uses one process/Worker, with runtime/import boot excluded (2,399.1 ms recorded). Comment nonces force source-fresh preparation but identical same-case Wasm can benefit from V8's internal code cache. First distinct module samples are retained separately; earlier cases still warm the engine. First execution is independently verified afterward but not separately timed, so lazy compilation there is excluded. JS compile/instantiate times are small in these observations, not proof of zero backend cost. Future engine-cold qualification requires a fresh browser process/temporary profile per sample or verified cache control, while runtime-ready source-fresh scope remains separate.

Research reduces uncertainty about the next changes; it does not establish a 4× speedup, native parity, new source support, full symbolic loop proof or safety of a future emitter. Acceptance requires actual implementation plus the plan's independent tests and controlled measurements.
