# Fast bounded compilation implementation

Implemented on `feat/fast-bounded-compilation`, compiler through `b5f7d2e`; final
serial qualification at clean revision `775930b`. This is a validated bounded
prototype with documented performance-target misses, not complete performance
qualification or a language-speed/parity claim. Lattice Core is a separate
compiler. Scalable v2/F1 remains **BLOCKED**.

The compiler now admits source once, structurally validates the three actual
candidate streams, ranks their exact costs, and normally proves only the winning
candidate. A live compilation-owned check authorizes emission. A separately
validated bounded loop hint must expand to that complete checked finite stream;
compact C and Wasm retain the loop structure. Public byte APIs still freshly
validate/check, and legacy selection, receipts and finite emission remain
compatible. An unmatched valid finite plan keeps the finite backend.

Request-local source facts reuse successful original-AST interpretations while
preserving accounting-v1 virtual allocations, work, witnesses and every quota
cutpoint. The structural validator avoids success-path diagnostic formatting.
The compact native kernel expresses the existing disjoint-buffer contract with
C11 `restrict`. It reduces input-invalid predicates for the valid fast path and
uses the original ordered scan on rejection, before scratch/output effects.
There is no persistent proof cache, hardcoded stencil replacement, lowered quota,
new source profile, compiler-flag change or shape-independent proof.

## Final measurements

All rows below have **21 samples** on the same shared Linux host. Before/after
order alternates. No unfavorable samples were removed or rerun. Browser cases
use fresh Chromium processes, temporary profiles and Workers; runtime/import
boot is excluded and retained separately. Native preparation includes fresh
source admission/proof/emission, C materialization and real Clang compile/link,
after Python imports. Input values are not embedded in generated code.

| 15×15 case | Before median / p95 | After median / p95 | Median speedup |
| --- | ---: | ---: | ---: |
| Browser, 64 B cap, inline | 617.6 / 713.2 ms | **150.7 / 165.0 ms** | **4.10×** |
| Browser, 128 B cap, two rows | 602.2 / 714.8 ms | **146.6 / 160.9 ms** | **4.11×** |
| Native, 64 B cap, inline | 604.9 / 671.2 ms | **187.8 / 196.0 ms** | **3.22×** |
| Native, 128 B cap, two rows | 521.2 / 566.8 ms | **184.3 / 199.6 ms** | **2.83×** |

Same-run direct build medians/p95: C **88.7 / 103.0 ms**, Rust **151.9 / 181.8 ms**.
The raw report is authoritative for exact values. Direct programs accept shape
at runtime; beryl specializes its declared shape and also proves/checks a plan.
These are different pipelines. Component medians are not additive: native
15×15 inline source preparation is 53.1 ms and compiler/link 131.7 ms, while the
continuous full-wall median is 187.8 ms. Compiler/link is the largest residual.

| Actual callable native kernel | Before ns/run | After ns/run | After / before median |
| --- | ---: | ---: | ---: |
| 1×1 inline | 7.294 | 6.480 | 0.888 |
| 5×7 inline | 58.319 | 34.461 | 0.591 |
| 15×15 inline | 320.360 | 306.574 | 0.957 |
| 15×15 two rows | 164.475 | 160.132 | 0.974 |

Each kernel sample performs one million changing-input external calls, without
LTO or process/Python overhead in the timed loop. Timed work includes mutation,
call, status/rotating-output capture and bookkeeping. All timed statuses and
rotating cells, complete final state and every replay output cell are independently
audited. Full replay assumes these generated kernels' deterministic/stateless
contract; every intermediate timed output cell is not captured. All four median
kernel guards pass. This does not say every pair or p95 improves.

Final public whole-process medians are roughly 0.76–0.82 ms, close to the same-run
C/Rust references. Those tiny programs mostly measure startup and I/O, so they
cannot replace the kernel experiment. Browser prepared requests include fresh
independent original-AST verification: the 15×15 medians are 14.6 ms ramp and
14.0 ms checkerboard, versus 13.9 and 13.2 ms before. Median and tail measurements
are distinct; several p95 values increased.

## Target outcomes and rollout ruling

Thresholds are retained exactly; a miss is not rounded into a pass.

| Engineering target | Final outcome |
| --- | --- |
| Browser ≥4× at both 15×15 caps | PASS, 4.10× / 4.11× |
| Browser ≤150 ms | cap64 **MISS, 150.7 ms**; cap128 PASS, 146.6 ms |
| Browser stretch ≤100 ms | MISS |
| Native ≤250 ms, stretch ≤200 ms | PASS at both caps |
| Native ≤2× each direct C/Rust build | C **MISS, 2.117× / 2.079×**; Rust PASS, 1.236× / 1.213× |
| Actual kernel median regression ≤10% | PASS for all four cases |
| Prepared verified browser median regression ≤10% | **MISS** for 1×1 ramp: 2.9 → 3.3 ms, 1.138×; other five PASS |
| Paired process median regression ≤10% | **MISS** for 1×1 checkerboard: 0.721931 → 0.799559 ms, 1.1075×; other five PASS |
| 15×15 C / Wasm bytes and locals ≥10× smaller | PASS |

The final inline C is 7,327 rather than 302,336 bytes; rows C is 11,767 rather
than 200,517 bytes. Wasm is 404 rather than 40,536 bytes with 18 rather than 3,376
locals; rows is 765 rather than 32,924 bytes with 10 rather than 2,344 locals.
These representation gains do not themselves prove a timing gain.

**Rollout ruling, 2026-10-18:** retain and publish the correct bounded prototype's
substantial compilation improvement under the user's existing bounded MIT
publication authorization, with this complete target table and rollback. This
is an explicit exception to the original plan's all-performance-gates rollout
wording, following the design's instruction to retain validated stages and report
misses. It does not waive or relabel any failed measurement. All source/proof,
quota, identity, memory, rejection-state, public-export and functionality gates
passed; the actual-kernel regression found in the first candidate was fixed and
remeasured. The few small-case latency misses remain real observations, without
asserting that they are statistically significant or merely noise. No general
C/Rust parity or full-performance-qualification claim is made.

The next native experiment should separate the strict I/O host from the small
kernel, measuring platform/toolchain identity, first infrastructure build/install
cost and actual kernel speed. It must not subtract first user-program work and
call that cold compilation. Profile small prepared-request/report overhead
separately before changing it. Those experiments are future work, not features
already implemented here. Larger shapes still require the separate complete F1
certificate and charged-work review.

## Validation and independent review

- Full regression discovery before the final native-only correction: 467 tests,
  445 executed successfully, 22 existing Core qualification/prerequisite skips,
  843.986 seconds. Bounded native C and real V8 tests ran; skipped Core tests do
  not establish Core native conformance.
- After the native-only correction: 22 focused real-Clang C tests passed,
  including meaningful LLVM `noalias`/vector-reduction checks, every invalid lane,
  both i32 extrema, multiple invalids, unchanged buffers, poisoned scratch and
  finite-byte controls. The full suite was not redundantly repeated.
- After that correction: 16 standalone public-ZIP/source-coordinator tests pass;
  17 UI/transport tests and browser-harness contracts pass. Real Chromium checks
  cover cold/reused source, reports, caps/objectives, all 256 input cells,
  cancellation/recovery, reset, keyboard/responsive layout and benchmark tables.
- Frozen expansion oracle covers all 955 shapes × three schedules. Complete-budget
  ranked winners/canonical bytes match legacy across all 14,518 cap/objective
  contexts. Source-fact results match the immutable original checker across all
  955 × three schedules and representative exhaustive joint quota prefixes.
- Independent task, residual, whole-integration, native-correction and final-data
  reviews are in [reviews](reviews). No material correctness/measurement defect
  remains; their performance limitations and failed targets remain explicit.

The first candidate failed actual kernel guards (5×7 1.2294×, rows 1.1013×).
[Initial evidence](initial-qualification/manifest.json) retains those failures.
[Native investigation](native-experiments/RESULTS.md) retains all rejected unroll,
noinline and scratch variants, RED/GREEN checks and the selected change. The final
source differs from that failed candidate; no unfavorable result was suppressed.

## Evidence and reproduction

[Machine-readable summary](qualification-summary.json) contains exact medians,
p95, ratios and failed targets. [Final raw manifest](final-qualification/manifest.json)
records both raw and stored hashes for compressed reports. Decode with Python's
`gzip.open`/`json.load` or `gzip -dc`. Raw reports retain sources, module/plan/C
identities, toolchain/flags, order, observations and independent audits.
`run.json` completing means orchestration completed, not all guards passed.

Private baseline is `39dc2f6df136c643cfd030ce4470503e807750fe`; the extracted archive
was separately checked against Git. Its report correctly has null observed Git
identity and a declared origin. Public baseline is the reviewed 13-module ZIP
`cb7304afabbfee94c4184f1c34574732f0f241c2a674222d6c3a8ee014bb6634`, recoverable
from public commit `149e4d6`. Final public bounded ZIP has exactly 23 modules plus
LICENSE, SHA-256 `bdea7e03ec93d3df176ba39a9670ffc6f45f754df7f83dcb68ba2ef788b243c6`.
No scalable research, Core binding, recovery/session record or private codename
enters that release. The final benchmark-data refresh changes no compiler bytes.

CPython 3.12.14; browser Pyodide 0.27.7/Python 3.12.7; Chromium 154.0.8037.57;
Clang 19.1.7 `-O3 -std=c11`, auto-loaded `clang.cfg` containing `-lm`; Rust 1.99.1
`-O`. Exact binaries, configuration, host/load and runtime hashes are retained.
Shared external host load, scheduler/GC variation and warm infrastructure limit
inference. These Linux observations do not predict the user's Windows hardware.

Use [the measurement guide](../../../../tools/benchmarks/compilation.md) and
[retained orchestration helpers](helpers). Helpers preserve exact historical
paths for provenance; adapt them explicitly on another host. For native:

```sh
python tools/profile-compilation.py --repo CANDIDATE --baseline-repo BASELINE \
  --baseline-revision 39dc2f6df136c643cfd030ce4470503e807750fe \
  --cc CLANG --samples 21 --diagnostics --output NEW.json
python tools/compare-playground.py --cc CLANG --rustc RUSTC \
  --compiler-archive REVIEWED_SITE/beryl-compiler.zip --samples 21 --output NEW.json
```

For fresh-browser large cases use `tools/benchmarks/compilation.cjs`,
`--mode engine-cold --samples 21 --diagnostics`, with the reviewed candidate and
baseline sites and the two 15×15 fixture IDs. The initial four-fixture 21-sample
run and final changed-package large-case run are separately retained. For native
kernels regenerate exact reviewed-ZIP artifacts with the retained helper, then
run `tools/measure-kernel.py` with `--iterations 1000000 --samples 21`.

The public comparison JSON preserves exact source/generated-C bytes and hashes;
only standalone absolute host/temporary path strings are reduced to basenames.
Its added compiler-default configuration records the actual `-lm` default.
Multiline source strings are not treated as paths. Public reports are descriptive
client-side evidence, not authoritative attestations.


## Published release

The bounded MIT package is live at [the beryl playground](https://nteuphoria.github.io/beryl-playground/),
public commit [`7d120b80ad7b326f1f13354748d19e902f4b5656`](https://github.com/NtEuphoria/beryl-playground/commit/7d120b80ad7b326f1f13354748d19e902f4b5656).
The [hosted hash verification](checks/hosted-release-hashes.json), recorded at
2026-10-18T05:32:45Z, confirms all 24 served files, including the compiler ZIP,
manifest and runtime assets, match the reviewed release byte for byte.
The [live HTTPS Chromium check](checks/hosted-browser-final.txt) passed all
18 recorded checks, including genuine runtime/Wasm execution, report download,
source/cap/objective changes, the 256th-input rejection, cancellation/recovery,
reset, responsive/keyboard behavior and saved/browser benchmark tables, with no
page errors. These are functionality checks, not another timing qualification.

The private implementation and evidence are reviewed in [PR #7](https://github.com/NtEuphoria/BerylLattice/pull/7).
Rollback remains the previous public commit
`149e4d6e9932008483cb4ae9b2c8458e19c4fe0e`. Publication changes none of the
measurement limitations or engineering-target misses above.
