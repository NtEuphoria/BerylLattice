# Native throughput investigation and selected change

Implemented commit: `b5f7d2ecfb4f89fe3ece34bfb4cca9d7d543f989`.
Only `axiom/src/axiom/bounded_loop_c.py`, `axiom/src/axiom/native_codegen.py`, and
`axiom/tests/test_bounded_loop_c.py` are in the commit. Controller-owned review
files were neither staged nor changed. No broad test suite was rerun.

The initial README describes the preparation phase. The controller subsequently
released serial compilation and seven-pair kernel experiments. This report and
`experiment-results.json` describe that later phase. Final 21-sample qualification
is owned by the controller and is not claimed by this report.

## Selected policy and reasoning

Compact emission opts in to C11 `restrict` on the two borrowed kernel parameters
and a vectorizable validity reduction. The public finite emitter defaults to its
exact previous header and preflight bytes. No optimization pragma, noinline
attribute, scratch initialization removal, stencil formula rewrite, or plan-label
special case was adopted.

The existing borrowed-array contract already requires initialized, exclusively
owned, disjoint arrays stable throughout the synchronous call. `restrict` exposes
this contract to alias analysis. The reduction reads the same exact bounded input
array and ORs its original lower/upper violation predicates. On valid input, this
has no scalar early exit, permitting Clang to use SIMD. If any predicate is true,
the unchanged ordered comparisons find and return the first invalid index + 1.
Both scans occur before scratch initialization or any plan primitive/output store.
All initialized output and input cells therefore retain their rejection-state
semantics. Plan order, widened arithmetic, scratch initialization, storage limits,
fresh admission and correspondence are unchanged.

The reduction uses original signed comparisons and an unsigned Boolean OR; it
introduces no subtraction-overflow trick or assumptions about bounds beyond those
already checked. Invalid inputs can cost an additional complete bounded scan.
The maximum input count remains 256 cells. Reads beyond the first invalid cell are
allowed because all cells are already required to exist, be initialized and remain
stable; volatile/concurrent/aliasing/lifetime-changing callers are outside this
existing contract.

## Root-cause evidence and rejected approaches

Clang 19 optimization remarks and assembly for old/new/restrict rows15x15 are in
`15x15-cap128/*-remarks.txt` and corresponding `.s` files. All inner column loops
were already fully unrolled (15 and 16 iterations), followed by SLP. The consumer
body used three four-wide groups, a two-wide group and a scalar, not an 8-vector /
7-scalar split. Its remaining outer row loop maintained parity-dependent scratch
addresses and repeatedly loaded/stored scratch memory.

Outer full unrolling removed enough repeated scratch work to beat baseline but
cost too much compiler time. Partial row unroll2 did constant-fold parity offsets
(the assembly has fixed scratch offsets), but retained scratch traffic and ran
slower. Thus merely eliminating parity arithmetic was insufficient. Forcing
consumer-only vectorization/interleave1 retained cheap compilation but slowed the
kernel. These results do not justify a general pragma or source-unrolling policy.

All kernel probes below used the existing external-call, separate translation
unit, no-LTO harness, one million changing-input calls per sample, seven alternating
pairs, independent formula replay and complete final-state audits. These are
probes, not the final 21-pair acceptance results. `experiment-results.json` records
source/result hashes and single object-compilation costs for every experiment.

| Case and variant | Candidate / baseline | Baseline ns | Candidate ns |
| --- | ---: | ---: | ---: |
| 5x7 restrict only | 0.71243 | 57.801 | 41.179 |
| rows15 restrict only | 1.10578 | 156.966 | 173.571 |
| rows15 inner unroll4 | 1.24190 | 170.241 | 211.422 |
| rows15 restrict + inner unroll4 | 1.24987 | 163.542 | 204.406 |
| rows15 restrict + row unroll2 | 1.12993 | 160.197 | 181.012 |
| rows15 restrict + uninitialized scratch | 1.10714 | 163.395 | 180.902 |
| rows15 restrict + row full unroll | 0.67104 | 162.038 | 108.734 |
| rows15 restrict + consumer vectorization | 1.15411 | 160.213 | 184.904 |
| **rows15 restrict + validity reduction** | **0.97885** | **158.849** | **155.489** |
| **inline15 restrict + validity reduction** | **0.96847** | **316.413** | **306.436** |
| **5x7 restrict + validity reduction** | **0.58703** | **60.477** | **35.502** |
| **1x1 restrict + validity reduction** | **0.94110** | **7.023** | **6.609** |

The full-row-unroll candidate's kernel object compile took 145.98 ms. Seven normal
executable compilations with `-O3 -std=c11` had median 191.76 ms; adding noinline
only reduced that to 187.66 ms, already beyond approximately 186 ms before the
frontend. The 15x15 inline restrict-only executable had median 120.79 ms, or
110.36 ms with noinline. These observations are in `compile-noinline-probe.json`.
Noinline did not rescue the rows budget, so it was not adopted.

For the selected reduction sources, seven executable compilations gave medians
137.43 ms (inline15) and 142.36 ms (rows15), with visible outliers up to 169/174 ms.
See `compile-preflight-reduction-probe.json`. These are compiler+link timings,
not complete cold-native latency. The controller must establish both <=250 ms
and <=2x the freshly measured C baseline for the complete pipeline. This report
does not waive or claim that gate. The selected rows object probe was 87.90 ms;
object timings must not be confused with full executable or pipeline timings.

The selected optimized rows LLVM IR is saved as
`15x15-cap128/restrict-preflight-reduction.ll`; it contains vector input comparisons
and `llvm.vector.reduce.or.v4i32`. Its main still calls `beryl_kernel`, so noinline
is not needed to preserve a host/kernel boundary in this observed candidate.

## Tests: RED, GREEN, compatibility and limits

1. `noalias-red.log`: the new O0 LLVM parameter-contract test failed for compact
   emission in all three schedules because `noalias` was absent. The finite-byte
   control passed. Compact-only restrict made the same contract test green.
2. `preflight-red.log`: with restrict alone, the new optimized LLVM reduction test
   failed because no `llvm.vector.reduce.or` existed in the kernel definition.
   The new complete-buffer invalid-lane test already passed, establishing the
   required old rejection behavior before changing preflight.
3. Reduction implementation made all 22 focused tests pass (`targeted-green.log`).
4. A proposed additional test using negative/cross-zero declared source intervals
   produced six `UNSUPPORTED_PROFILE` errors: this frontend deliberately admits
   only the canonical 0..1023 stencil profile. This out-of-profile test was removed
   without modifying admission. `targeted-final-green.log` preserves that failed
   exploratory run; it is NOT the final verification log.
5. `targeted-final-22-green.log`: **22 tests passed in 7.554 s**, real Clang 19,
   no skips. This is the final run after removing the unsupported fixture.

Final command:

```sh
AXIOM_TEST_NATIVE_CLANG=/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang \
PYTHONPATH=axiom/src:axiom \
python -m unittest tests.test_bounded_loop_c tests.test_native_codegen -v
```

The new parameter-contract test compiles actual emitted compact and public finite
C at O0, extracts `beryl_kernel`'s two parameters, and checks both explicit noalias
attributes. O0 prevents optimizer inference from masking a missing qualifier. The
finite control must have neither. The new optimized preflight test looks inside
the kernel definition for vector comparisons and a vector OR reduction, so a
matching word in the I/O driver cannot satisfy it.

The new rejection test exercises every input position across vector lanes and the
partial group, with INT32_MIN, -1, 1024, INT32_MAX, simultaneous later invalids,
nonzero distinct output sentinels, full input/output comparison, and valid calls
between rejected calls. Existing tests retain scratch poison/canaries, all
schedules, boundary shapes, complete observations against two independent
interpreters, dead widened arithmetic, and deliberately faulty emitter controls.

New fixed finite digests for all three schedules catch accidental shared-helper
byte changes. `production-byte-check.json` additionally shows the actual current
source compiler emits exactly the four measured compact probe files. The four
finite outputs equal original public artifacts after applying only the existing
public namespace banner transformation. Public/package semantic digests differ
by design, so the helper does not pretend checkout and public plan bytes are
identical. The controller still needs to rebuild and qualify the final public ZIP.

`git diff --check` passed before commit. No C or test processes remain owned by
this investigation; the serial measurement slot was explicitly released to the
controller immediately after commit.
