# Scaling beryl: template proofs and loop plans (scale-v1)

Status: phase 1 implemented on `feat/bench-native`. Follows
`docs/superpowers/specs/2026-10-19-reductions-design.md`.

## Problem

Every admitted program today holds at most 256 input cells, because every proof step grows with the
data:

- **plans** are flat operation lists, one entry per scalar operation, so their size grows with H, W
  and the sum range;
- **the checker** rebuilds the expected value of every output cell symbolically and compares
  node by node;
- **compact loop hints** are untrusted, so they are expanded and matched op by op, and the proof
  costs as much as the unrolled plan;
- **the native backend** uses fixed stack arrays.

Raising the cap without changing the method makes compile time and memory grow with the data, which
is the DoS the proof-boundary review measured.

## Key fact

Every equation in the admitted families is **uniform over its axes**. Cell `(r, c)` evaluates the
same expression template, and indices are affine in `r`, `c` and summation variables. Inputs share
one interval. So:

- the value of every cell is the template evaluated at affine indices;
- the interval of every scalar node is the same for every cell, so overflow can be proved once per
  template;
- every read's bounds are a box over affine indices, so one corner check covers all cells.

A plan that is itself a loop nest over the same template can therefore be proved in
`O(template size)`, independent of H, W and sum ranges.

## Phase 1 (this change)

### Language

`sum(k in L..U: e)` keeps its definition, a balanced `+` tree, for at most 256 terms. Above 256 terms
(up to 2^24) it is **symbolic**: the exact integer sum of its terms. It is admitted only when the
checker proves that every partial sum, in any order, fits i32: `n * max|term| <= 2^31 - 1`. Because
no association can overflow, the value is association-free, and the plan or the C compiler may
reorder or vectorize the accumulation. A symbolic sum variable may be used only in indices.

### Family `scale-v1`

The structure of reduce-v1 (two shapes, one or two `i32` inputs in `0..=1023`, one producer, one
output) with:

- **sizes** up to 2^24 cells per tensor;
- **producer read indices**: literals plus at most one axis plus any number of sum variables, all
  coefficient 1;
- **output read indices**: the own axis plus sum variables plus a literal offset.

It is tried only after the canonical, window and reduce-v1 families, which keep their admission and
identities. Semantic version `scale-i32-v1`; the semantic record names the symbolic-sum rule.

### Loop plans (`beryl-loop-plan-v1`)

```
LoopPlan(semantic_digest, plan_id, stages)
Stage(loops=((var, extent), ...), index=Affine, value=Expr)    # stores into the output
Expr  = ('const', v) | ('load', Affine) | ('add'|'mul', Expr, Expr) | ('sum', var, lo, hi, Expr)
Affine = (constant, ((var, coefficient), ...))                 # canonical, sorted
```

Phase 1 has one schedule, `direct-v1`: one stage over `r in 0..H, c in 0..W` storing `r*W + c`, with
the producer inlined.

### Template checker (independent, trusted)

It re-admits the source from its bytes, then proves:

1. **Coverage:** exactly one stage, loops `(H, W)` with distinct fresh variables, store index exactly
   `v0*W + v1`. Every output cell is written exactly once.
2. **Equivalence:** the plan expression equals the source template, structurally.
   - Input reads equal `load(base + row*cols + col)` as canonical affine forms.
   - Producer reads are matched against the producer template under substituted indices.
   - Sums match variable (by binding), range and body.
   - No algebra is used: association and operand order are exact.
3. **Bounds:** every load's affine minimum and maximum over its variable box lies in
   `[0, input_count)`, a defence in depth on top of admission's per-dimension bounds.
4. **Arithmetic:** interval analysis over the template from the input interval. Every `+` and `*`
   node fits i32. Every symbolic sum satisfies the partial-sum bound.

Cost is linear in the template, with producer inlining counted, and bounded by a step quota.

### Emission

C loops, emitted only from a checked plan. A branch-free input preflight runs first, then the loop
nest, with symbolic sums as inner accumulation loops.

- Arithmetic is plain `int32_t`; the checker's interval proof rules out overflow, so there is no UB.
- Parameters are `restrict`, and the driver uses static buffers.

### Not yet scaled

These keep their current paths: the playground and Wasm, the Python plan runtime, and the
interpreted `axiom` benchmark column.

### Phase 1 results

**Proof cost is flat in size.** A 20x20 and a 2000x2000 stencil take the same number of checker
steps (49), as do a 1,000-term and a 1,048,576-term sum (`test_proof_cost_does_not_grow_with_size`).
Compile time, admission plus proof plus C emission plus clang, is about 0.2 s at every size;
matmul at 256 takes 0.5 s.

**Correctness.**
- On good and bad inputs (first, middle and last cell, including the second input), the Python
  loop-plan runtime agrees with the reference evaluator for six programs.
- Native C agrees with the reference for four of them; Application Control refused the other two
  executables.
- Every benchmark run matched the oracle checksum.
- The checker rejects 12 kinds of forged plan, and both overflow cases.

**Benchmark** (`hash` pattern, same session, ns medians). "hand C" is the like-for-like control: the
same i32 interface, harness and flags. The plain C baselines write i64 outputs.

| Kernel | tier | axiom-native | C | native/C | hand C | native/hand |
|---|---|---|---|---|---|---|
| sq2x2 | m 255x255 | 54,678 | 111,825 | 0.49 | 61,640 | 0.89 |
| sq2x2 | l 2047x2047 | 4,584,250 | 7,346,950 | 0.62 | 4,922,700 | 0.93 |
| stencil1d3 | m 65534 | 18,043 | 41,528 | 0.43 | 26,362 | 0.68 |
| stencil1d3 | l 4194302 | 3,314,300 | 3,957,500 | 0.84 | 3,663,600 | 0.90 |
| box3x3 | m 254x254 | 32,356 | 102,984 | 0.31 | 40,993 | 0.79 |
| box3x3 | l 2046x2046 | 3,711,100 | 6,954,900 | 0.53 | 3,860,000 | 0.96 |
| laplace5 | m | 22,268 | 65,399 | 0.34 | 31,436 | 0.71 |
| laplace5 | l | 3,354,050 | 4,538,700 | 0.74 | 3,911,200 | 0.86 |
| conv3x3 | m | 32,620 | 145,387 | 0.22 | 42,365 | 0.77 |
| conv3x3 | l | 3,525,600 | 9,362,400 | 0.38 | 3,849,350 | 0.92 |
| polymap | m 65536 | 30,341 | 44,468 | 0.68 | 38,423 | 0.79 |
| polymap | l 4194304 | 3,421,100 | 4,112,700 | 0.83 | 3,954,500 | 0.87 |
| transpose | m 256x256 | 77,715 | 401,875 | 0.19 | - | - |
| transpose | l 2048x2048 | 34,548,300 | 58,712,000 | 0.59 | - | - |
| sum | m 65536 | 8,465 | 15,115 | 0.56 | - | - |
| matmul | m 64 | 50,359 | 150,974 | 0.33 | - | - |
| matmul | l 256 | 18,363,800 | 9,726,250 | **1.89** | - | - |

Not yet:
- **Refused by the overflow proof.** sum l (4M x 1023 > 2^31) and dot m/l need i64 accumulators
  (phase 2). *Done 2026-10-24: see "Phase 2: i64 equations" below.*
- **matmul l is slower than C.** Its 256-term sum is expanded into one 256-product expression per
  output, while C runs a cache-friendly i-k-j loop. Loop-order and tiling schedules (phase 3) are
  the fix.

## Roadmap

| Phase | Adds | Unlocks |
|---|---|---|
| 1 | template proofs, loop plans, native C loops, symbolic sums | m/l tiers of stencils, polymap, transpose, sum, matmul |
| 2 | element types (`i64` equations and outputs), per-input intervals, `u8`/`i8`/`i16` storage (done, Phase 2e) | dot, large sums, any input range, int8 and int16 arrays |
| 3 | schedules with proof rules: materialized producer, rolling rows, tiling | separable stencils without recomputation, cache-blocked matmul |
| 4 | loop plans in Wasm and the Python runtime; playground at scale | interactive large programs |
| 5 | language: `max`/`min` (done, Phase 2c), right shifts and rounding (done, Phase 2d), comparisons and `select`, strided indices, several equations | maxpool, requantize, life, scan |

Every phase that changes what is admitted or how plans are trusted gets an independent review
before it is relied on.

## Hardening after an external review, and split2 (2026-10-31)

An external review (Codex, of `0341abe`) reproduced four problems in the gap between the
checked plan and the code that runs. All four are fixed, each with a test that failed first,
and each fix was then attacked by a separate verifier with probes of its own.

**1. Untrusted plan text could reach the C** (security).
- The problem:
  - `plan_id` was pasted into a C comment, so a candidate plan could close the comment and
    inject code that the candidate demo then compiled and ran.
  - Plan variable names were emitted as C identifiers, so a proved plan could name a
    variable `acc` or `x; }`.
- The fix: `scale_c._emitter_plan` rebuilds every plan from the emitter's own strings before
  any C is written.
  - Variables become `r`, `c`, `p`, `q`, `s0`, `s1`, … (the planner's own scheme), and each
    sum binding gets a fresh name.
  - Integers must be plain ints.
  - The header names a plan only when its ID is exactly one of `SCALE_PLAN_IDS`; otherwise it
    says "candidate".
- The planner's plans emit byte-identical C.
- Tests: `tests/test_scale_untrusted.py`. With the fix removed: 305 failures and 56 errors.
- The verifier tried 17 hostile plan IDs and hostile names over every binding: comment
  escapes, `#define`, keywords, emitter-internal names, Unicode, a 5,000-character name. No
  attacker byte reached the C. Accepted plans matched the reference in WSL at 4 threads.

**2. Concurrent calls into one parallel kernel gave wrong results** (correctness).
- The problem: the pool's job state is global. Two callers produced 11 wrong results in 40.
- The fix: each pooled call holds a process-wide lock for its whole duration. The lock is
  statically initialized (`PTHREAD_MUTEX_INITIALIZER`, `SRWLOCK_INIT`) and released on every
  return path by a cleanup attribute. A one-thread pool releases it at once.
- Calls into one compiled parallel kernel are now serialized within a process. Separate
  kernels have separate pools.

**3. Invalid inputs could overflow before rejection** (undefined behaviour).
- Paths that compute before the check is acted on added rejected values in signed
  arithmetic. UBSan trapped on three of them:
  - the split sum's partial (found here first);
  - the pooled combine of partials, `total += beryl_job_partial[c]`;
  - the scalar tail of `beryl_dot_u8i8` under the fused contract (n ≥ about 66,000 terms).
- The fix: all three add modulo 2^N (`_wrapping`). Where the proof's ranges hold, nothing
  wraps, so the results are unchanged.
- Tests:
  - `tests/test_scale_invalid_extremes.py`: 39 native tests over every emission path, with
    several invalid extremes at once (two INT32_MAX, INT32_MIN, one past each bound, at the
    first, middle and last index). They check the exact status and, under the default
    contract, unchanged output. All pass under ASan+UBSan with every report fatal.
  - `tests/test_scale_split2.py` covers the split sum.

**4. Idle workers burned CPU** (performance).
- The problem: after one call, the four-thread pool used 2.92 CPU-seconds in 1.02 s idle.
- The fix: idle workers spin a bounded 2^14 pauses, then block on a condition variable. A
  sleeper count means a dispatch pays the wake-up only when someone is asleep.
- Idle CPU fell from about 3.0 s to about 0 per idle second.
- Tests: `tests/test_scale_pool_concurrency.py`, with concurrent callers and an idle-CPU
  limit. They pass under plain gcc, ASan+UBSan and TSan.
- Open: a small two-dispatch kernel may have lost a little latency (51 against 67 µs in
  half the rounds), but that is not established; both pools show the same two modes.

**split2: whole-input sums.** Each fused split sum now:
- checks by bitwise OR when its span is 2^k − 1 (values lie in `0..=span` exactly when their
  OR does). Otherwise it keeps the unsigned maximum. An OR can only over-report, and a false
  flag costs a rescan, never a wrong status.
- hints `_Pragma("GCC unroll 4")`, because gcc vectorized the sum but kept one vector per
  iteration.

**Versions.**

| tag | programs | why |
|---|---|---|
| `-split2-` | whole-input split sums | OR check, unroll hint, wrapping |
| `-pool2-` | every parallel program | lock and blocking workers |
| `-madd2-` | the u8 × i8 dot | wrapping tail |

- Of the 13 byte-identity programs, the 8 parallel ones changed C behind `pool2`.
- The 6 serial ones are byte-identical.
- Every semantic digest is unchanged.

**Against hand-written AVX2** (`bench/impl/hand/sum.c`, `dot.c`: one pass, OR check, four
accumulators, `vpmaddwd` for dot, same ABI and harness; `bench/test_hand_avx2.py`). Five
interleaved rounds, one thread, WSL gcc `-O3 -march=native`, median:

| kernel | before split2 | split2 | hand AVX2 | split2 vs hand |
|---|---|---|---|---|
| sum, 64K values | 2,961 ns | 2,517 ns | 2,511 ns | 1.00x |
| dot, 32K pairs | 2,953 ns | 2,604 ns | 2,528 ns | 1.03x |
| sum, 4M values | 1.20 ms | 1.10 ms | 1.11 ms | 0.99x |
| dot, 2M pairs | 1.00 ms | 1.03 ms | 1.01 ms | 1.02x |

- Before split2, beryl took 1.17–1.18x the hand code's time in cache.
- Now it is within 3% everywhere; the large sizes are memory-bound and tie.

## Phase 6a: u8 × i8 dot products through the pair multiply-add (2026-10-30)

Phase 6 of `2026-10-25-ml-scale-cpu-core-design.md`, first part. Phase 5 was skipped after
measurement: tiling does not help int32 matmul on this CPU (see that design's progress
log).

**The rule.** The emitter finds a sum whose body is a u8 load times an i8 load, both
stepping one cell per term: a dot product along the sum, as in a dense layer with weights
stored `[out, in]`. It replaces the sum with `beryl_dot_u8i8(p, q, n)` when all three hold:
- **The pair bound.** AVX2's `vpmaddubsw` multiplies 32 byte pairs and adds neighbouring
  products, saturating at i16. It is exact only when every pair sum fits i16. The emitter
  requires `2 × (u8 maximum) × (largest |i8|) ≤ 32767`, from the declared input ranges.
  With weights in `-127..=127`, activations up to 129 qualify; 130 does not.
  - Activations in `0..=127` qualify with any i8 weights. This is what FBGEMM's
    reduced-range quantization uses on x86 for the same reason.
- **The sum fits int32.** For an i32 sum the checker's proof already says so. In an i64
  program, the sum must fit one exact int32 block (`_narrow_block`).
- **Exact partial sums.** The helper adds pairs with `vpmaddwd` against ones (exact) and
  accumulates eight int32 lanes. Each lane holds a partial sum of the terms, which the
  proof bounds too.

The helper keeps plain C for the tail, and for builds without AVX2.

**My call: an emission rule with its own interval check, not a checker-carried mark.** The
design called for plans to carry width marks that the checker proves. This rule derives the
same fact from the same declared ranges inside the trusted emitter, as the exact int32
blocks of i64 sums already do. It joins the "argued and tested" list. Checker-carried marks
come back when a planner proposes alternative widths.

Codegen is `beryl-loop-c-madd-...` where the rule applies. Every other program is unchanged:
byte-identical C and digests for the 13 checked programs.

**Speed** (WSL, gcc `-O3 -march=native`, Ryzen 3 3100, beryl's own kernels through ABI 2;
dense layers, weights `[out, in]`).

| layer | i8 × i8 | u8 × i8, activations to 255 | **u8 × i8, activations to 127** | i16 × i16 |
|---|---|---|---|---|
| 256 × 256 × 256, 1 thread | 690 µs | 725 µs | **329 µs** | 434 µs |
| 4096 → 11008, one row, 1 thread | 9.18 ms | 9.20 ms | **2.92 ms** | 12.4 ms |
| 1024³, 1 thread | 71.2 ms | 71.5 ms | **21.3 ms** | 41.7 ms |
| 1024³, 4 threads | 23.4 ms | 23.9 ms | **7.6 ms** | 13.2 ms |

- That is 2.1–3.4x faster than today's int8 path, and faster than i16.
- At 256³ it is 0.85x the time of OpenBLAS `sgemm` (float32, one thread, 388 µs). That is
  int8 against float32, so it is not a like-for-like claim.

**Against PyTorch's int8 path (2026-10-30).**
- Setup: PyTorch 2.15.0+cpu in `.local/torchenv`, WSL, same machine, same timing method
  (the median of 9 runs of about 0.1 s).
- FBGEMM is `torch.ops.quantized.linear`, with activations quint8 in `0..=127`, weights
  qint8, prepacked once outside the timing.
- beryl is the u8 × i8 multiply-add kernel above, through ABI 2.
- Ranges cover three runs each, measured in the same session.

| layer | beryl | FBGEMM | beryl's speed vs FBGEMM |
|---|---|---|---|
| 256³, 1 thread | 324–330 µs | 358–392 µs | 1.1–1.2x; a tie after FBGEMM's ~20 µs call cost |
| 4096 → 11008, one row, 1 thread | 2.91–3.42 ms | 3.51–5.46 ms | 1.0–1.9x; memory-bound, noisy |
| 1024³, 1 thread | 21.3–22.2 ms | 22.0–22.4 ms | a tie, within 5% |
| 256³, 4 threads | 114–126 µs | 184–308 µs | 1.5–2.7x |
| 4096 → 11008, one row, 4 threads | 1.69–2.08 ms | 1.99–3.42 ms | 1.0–2.0x; memory-bound, noisy |
| 1024³, 4 threads | 7.45–7.70 ms | 8.32–8.90 ms | 1.1–1.2x |

- **The phase 6 target is met: at or above FBGEMM on one thread, at every size.**
  - The honest summary is "on par".
  - At 1024³, where compute dominates, they tie.
  - beryl leads clearly only on small four-thread layers.
- **Not like for like, in both directions:**
  - beryl checks every activation against `0..=127` before computing; FBGEMM checks
    nothing.
  - FBGEMM requantizes each output to u8. That is one step per output, negligible next to
    the multiply-adds.
  - FBGEMM's weights are repacked into its own layout ahead of time. beryl reads them as
    stored, `[out, in]`.
  - FBGEMM is called through Python, about 20 µs per call (measured on a 1 × 16 × 16
    layer). That cost only matters at 256³.
  - Both use the same instruction pair (`vpmaddubsw`, `vpmaddwd`). The reduced activation
    range exists for the same saturation reason.
- **`torch._int_mm` (int8 × int8 to int32) is not a baseline on CPU.** It ran 13 ms at 256³
  and 0.8–1.1 s at 1024³, 30–50x slower than FBGEMM: an unoptimized fallback. Quoting beryl
  against it would mislead, so we don't.
- The 4096 → 11008 layer streams 45 MB of weights per call, so memory bandwidth bounds it.
  Its run-to-run spread is wider than the gap between the two.
- Scripts and logs: `.local/phase6/torch_bench.py`, `overhead.py`, `run_madd.sh`, and
  `torch_bench*.log` / `madd_rerun*.log` (git-ignored).

**Rerun on the hardened compiler (2026-10-31).** This run uses `pool2` and `madd2` (see
"Hardening after an external review"), with nothing else running. Three interleaved rounds;
FBGEMM without `_int_mm`. Log: `.local/phase6/quiet2.log`. Checksums are identical to the
earlier runs.

Ratios are computed round by round: FBGEMM's time over beryl's in the same round. The
"net" column first subtracts FBGEMM's ~20 µs Python call cost from every FBGEMM time.
(Corrected the same day: a first version paired extremes across rounds and subtracted the
call cost at 256³ one thread only.)

| layer | beryl | FBGEMM | ratio, raw | ratio, net |
|---|---|---|---|---|
| 256³, 1 thread | 325–331 µs | 364–379 µs | 1.10–1.17x | 1.04–1.11x |
| 4096 → 11008, one row, 1 thread | 2.81–3.02 ms | 3.25–3.51 ms | 1.07–1.25x | 1.07–1.24x |
| 1024³, 1 thread | 21.67–21.75 ms | 21.29–21.85 ms | 0.98–1.00x | 0.98–1.00x, a tie |
| 256³, 4 threads | 119–129 µs | 187–196 µs | 1.45–1.58x | 1.30–1.42x |
| 4096 → 11008, one row, 4 threads | 1.72–1.73 ms | 2.01–2.15 ms | 1.17–1.24x | 1.15–1.23x |
| 1024³, 4 threads | 7.15–8.60 ms | 8.28–9.38 ms | 1.08–1.30x | 1.08–1.30x |

- With idle workers now blocking, beryl's four-thread spread is much narrower than in the
  first run (where 1024³ ranged from a 0.83x loss to 1.96x).
- **One thread, 1024³ is still a tie**, the honest headline: the same instruction pair,
  near this CPU's limit.
- The like-for-like caveats above still apply:
  - beryl range-checks every activation; FBGEMM checks none;
  - FBGEMM requantizes to u8, uses prepacked weights and is called through Python.
- The full-range exact path (activations to 255) at 256³, one thread: 688–699 µs, against
  325–331 µs for the fast pair. That is 2.1x.

**Verification.**
- `tests/test_scale_madd.py`: 5 tests, written first and failing before the change. They
  cover:
  - the exact range boundary (129 qualifies, 130 does not);
  - i8 × i8, u8 × u8 and a strided weight layout, none of which qualify;
  - the portable fallback;
  - native runs: hashed data with a 12-term tail and a parallel layer, plus every pair at
    ±32766, one short of saturating.
- **Red check:** without the pair bound, activations of 255 against weights of 127
  saturate, and the native test fails (outputs about 5.0M instead of 9.6M).
- In WSL (gcc), 4 programs, the full 4096 → 11008 layer included, ran 36 cases at 1 and 4
  threads.
  - With AVX2, plain, under TSan and under ASan+UBSan: 216 runs, all clean.
  - Built without AVX2, which runs the portable fallback: 72 runs, all clean.
- The full suite (645 tests) has no new failures: the same four unexplained failures as
  before, and known Windows causes for the rest.

## Phase 4b: compute, then check, in wrapping arithmetic (2026-10-30)

Phase 4's blocks read their input twice: a check pass from memory, then the compute pass
from cache. On one thread that kept large kernels 13–23% above unchecked. 4b swaps the
order inside each block.

**What changed.**
- Each block computes first, reading its input from memory, then checks the same share of
  input while it is still in cache. The shares are as in Phase 4, so every input cell is
  still checked, in any block order and on any thread.
- A block may now compute on values its check then rejects. So under the fused contract,
  every `+`, `*` and sum wraps: `(int32_t)((uint32_t)a + (uint32_t)b)`, and `uint64_t` for
  i64.
  - Unsigned arithmetic cannot overflow. The conversion back is modulo 2^N on the
    supported compilers: implementation-defined in C11, never undefined.
  - Wherever the proof's ranges hold, nothing wraps, so results are exact.
  - On rejection the output is garbage, which the contract allows, and the status stays
    exact.
- A static assertion that `int` is at most 32 bits guards the wrapping: otherwise
  `uint32_t` operands would promote to signed `int` and could overflow.
- Values are never used as indices, and narrow stores of garbage are
  implementation-defined conversions. So no other undefined behavior can follow from a
  bad value.
- Programs without the contract are unchanged: byte-identical C and digests for the 13
  checked programs. Fused programs move to codegen `beryl-loop-c-fused2-...`.

**Speed** (as in Phase 4: WSL, gcc `-O3 -march=native`, 64K-cell blocks, the minimum of two
interleaved rounds).

| kernel | threads | default | fused | unchecked | fused / unchecked | default / fused |
|---|---|---|---|---|---|---|
| map m | 1 | 9.0 µs | 9.5 µs | 5.9 µs | 1.59 | 0.95 |
| map l | 1 | 3.41 ms | 2.46 ms | 2.26 ms | 1.09 | 1.38 |
| map l | 4 | 2.53 ms | 1.97 ms | 1.93 ms | 1.02 | 1.28 |
| box (carry) l | 1 | 3.71 ms | 3.03 ms | 2.90 ms | 1.05 | 1.22 |
| box (carry) l | 4 | 2.52 ms | 1.91 ms | 1.89 ms | 1.01 | 1.32 |
| diag stencil l | 1 | 3.20 ms | 2.50 ms | 2.33 ms | 1.08 | 1.28 |
| diag stencil l | 4 | 2.48 ms | 1.97 ms | 2.00 ms | 0.99 | 1.25 |
| one row l | 1 | 2.74 ms | 1.91 ms | 1.75 ms | 1.09 | 1.43 |
| one row l | 4 | 1.65 ms | 1.17 ms | 1.16 ms | 1.01 | 1.41 |

- **Large data, four threads:** within 2% of unchecked for all four kernels; the one-row
  kernel was 11% over in Phase 4.
- **Large data, one thread:** 5–9% above unchecked, down from 13–23%, and 1.22–1.43x
  faster than the default check. **Still short of the 5% target on one thread.**
- **In cache:** unchanged, 25–60% above unchecked on one thread, and about the same as the
  default check. The check's arithmetic does as much work per value as these kernels do,
  and fusing cannot remove it. A cheaper check is the remaining lever; for example, a
  range `0..=2^k - 1` could be checked with one OR per value instead of a subtract and a
  max.
- 4K, 16K and 64K blocks again measured within noise of each other, so the block stays at
  64K.

**Verification.**
- `tests/test_scale_contract.py` now has 8 tests. The new emission test (wrapping
  arithmetic, compute before check) failed before the change.
- The native cases add the far end of each input's storage type, such as `INT32_MAX`.
  Arithmetic on that overflows.
- In WSL (gcc), 16 builds of 92 cases ran plain, under TSan and under ASan+UBSan, at 1 and
  4 threads: 552 runs, all clean.
- **Red check:** the same builds with wrapping turned off fail under UBSan, on the extreme
  case of every fused program. The transpose keeps the up-front check and stays clean.
- The full suite (640 tests, the restored fused-sum tests included) has no new failures:
  the same four unexplained failures as before, and known Windows causes for the rest.

## Phase 4: the fused contract (2026-10-29)

Phase 4 of `2026-10-25-ml-scale-cpu-core-design.md`. Programs without the new line keep
their identity and their C: all 13 checked programs are byte-identical, and so are their
semantic digests.

**The contract.** `require output_on_rejection = unspecified;` says the output is
unspecified when the kernel rejects its input. The status is unchanged: 0, or the exact
first bad index plus one.
- The line adds `output_on_rejection` to the semantic record. It is accepted once, with
  this spelling only, and only in a scale-v1 program; a small program that declares it is
  admitted as scale-v1.
- The Python reference and the loop-plan runtime still return the original output on
  rejection. That is one of the allowed outputs.

**Block by block.** Each block of output is checked just before it is computed, so it reads
its input once, while that input is in cache.
- Block `[o, e)` checks each input from the cell where output `o` starts reading, up to the
  last cell the block reads. The last block checks up to the input's end.
- These shares tile every input, overlapping by a few rows. So every input cell is checked,
  in any block order and on any thread, and no block is computed before the cells it reads
  are checked.
- A block that finds a bad value stops. The kernel then runs the ordered scan for the exact
  first bad index, as before.
- Inputs that no load reads are checked whole, before any block.
- The bounds hold when every load of an input has the same nonnegative row and column
  coefficients, with the row step at least a row's width of columns. Then both ends of a
  block's reads never decrease as the block moves on. Maps, stencils, carry plans and
  one-row kernels qualify.
- Transposes, matrix multiplies, dense layers and single-cell sums keep the up-front check,
  which the contract also allows. Their reads do not advance with the output row.
- A block is at least 64K output cells, or 64K cells of rows for a carry plan. It doubles,
  up to four times, until its fresh input is at least four times what it rechecks at its
  edges. 4K, 16K and 64K blocks measured within noise of each other.
- Codegen is `beryl-loop-c-fused-...`, with the ABI and parallel variants.

**Speed** (WSL, gcc `-O3 -march=native`; the unchecked twin is the default C with the check
function stubbed out, for measurement only; m is 64K cells, l is 4M cells).

| kernel | threads | default | fused | unchecked | fused / unchecked | default / fused |
|---|---|---|---|---|---|---|
| map m | 1 | 9.2 µs | 9.8 µs | 6.1 µs | 1.61 | 0.94 |
| map l | 1 | 3.40 ms | 2.88 ms | 2.39 ms | 1.21 | 1.18 |
| map l | 4 | 2.66 ms | 2.05 ms | 2.01 ms | 1.02 | 1.30 |
| box (carry) m | 1 | 17.0 µs | 17.4 µs | 13.9 µs | 1.25 | 0.98 |
| box (carry) l | 1 | 4.14 ms | 3.22 ms | 2.85 ms | 1.13 | 1.28 |
| box (carry) l | 4 | 2.74 ms | 2.06 ms | 2.01 ms | 1.02 | 1.33 |
| diag stencil l | 1 | 3.35 ms | 2.88 ms | 2.40 ms | 1.20 | 1.17 |
| diag stencil l | 4 | 2.68 ms | 2.09 ms | 2.02 ms | 1.03 | 1.28 |
| one row l | 1 | 2.93 ms | 2.27 ms | 1.85 ms | 1.23 | 1.29 |
| one row l | 4 | 1.84 ms | 1.40 ms | 1.25 ms | 1.11 | 1.32 |

- **Four threads:** within 5% of unchecked in 7 of the 8 cases (four kernels, two sizes).
  The exception is the one-row l kernel, 11% over. That meets the target, with that
  exception.
- **One thread, large data:** 1.17–1.29x faster than the up-front check, but 13–23% slower
  than unchecked. **The target is missed here.**
- **One thread, in cache:** about the same as the up-front check, and 25–61% slower than
  unchecked. The check's own arithmetic is the cost here: it does about as much work per
  value as a map. Fusing saves only the second read.
- **What would close the gap:** a single pass, where each block computes and checks in the
  same loop. Reading values before they are checked is safe only if a bad value cannot
  cause undefined behavior, so the block would compute in wrapping (unsigned) arithmetic.
  The contract allows the garbage that results on rejection. Cells that no load reads would
  still need the block shares. This is the follow-up, Phase 4b.

**Verification.**
- `tests/test_scale_contract.py`: 7 tests, written first and failing before the change. They
  cover:
  - the spelling and admission;
  - emission choices;
  - native runs of 9 programs, through both ABIs, at 1 and 4 threads.
- The native runs are on good data, and with bad values at the first, middle and last cell
  of every input, plus an unread column. The status must be exact.
- In WSL (gcc), 16 builds of 74 cases ran plain, under TSan and under ASan+UBSan, at 1 and 4
  threads: 444 runs per block size. All are clean at 16K and at 64K blocks.
- The 105 related tests pass.
- The full suite (636 tests) has no new failures: the same four unexplained failures as in
  3a and 3b, and known Windows causes for the rest. Application Control blocked nothing
  this time.
- These runs missed the three older fused-sum tests in `tests/test_scale_fused.py`: the new
  tests had overwritten that file by mistake. The file is restored, and those three tests
  pass on the final code.

## Phase 3b: one pointer per input (ABI v2) (2026-10-26)

The rest of phase 3 of `2026-10-25-ml-scale-cpu-core-design.md`. Programs admitted before
keep their identity and their interface: the generated C of all 13 checked programs is
byte-identical to 3a's, and so are their semantic digests.

**What is admitted.**
- Up to four inputs, each with its own storage type: for example u8 activations, i8 weights
  stored `[out, in]`, an i32 bias and an i16 per-channel scale.
- The 2^31 − 1 limit is per tensor. Inputs may pass it together.
- A program whose inputs mix storage types adds `input_storage` to its semantic record.
  Programs whose inputs share one type keep their record unchanged.
- The Python reference, the loop-plan runtime and the sampled reference check each input's
  values against that input's own storage type.

**The interface.**
- ABI 1 is unchanged: `int32_t beryl_kernel(const T *input, OUT *output)`, the inputs joined
  in declaration order. It stays the default wherever it fits.
- ABI 2 is `int64_t beryl_kernel_v2(const T0 *in0, ..., OUT *output)`, one pointer per
  input. The status means the same: 0, or the first bad cell's index in the joined order
  plus one.
- ABI 2 is required for mixed storage types, and for more than 2^31 − 1 input cells in
  total. Any other program can ask for it with `compile_scale_native(source, abi=2)`. It
  then also keeps a `beryl_kernel` wrapper that passes offsets into the joined buffer, so
  existing drivers keep working.
- Codegen is `beryl-loop-c-abi2-v1` (and `-parallel-abi2-v1`), so ABI 1 output keeps its
  version.
- Every emission path takes the per-input pointers: plain cells, row accumulation,
  per-cell sums, tiles, streaming stores, carry rows, and the split single-cell sum with its
  fused check. The thread pool passes them as an array.
- The input check is one unsigned maximum per value, per input, typed to its storage type.
- The standalone driver reads each input's tokens as that input's type. A token that does
  not fit is refused (exit 65); a value outside its declared range gives exit 66.

**A fix found on the way.** The emitter named a load's input by its constant term. In
`y[0, j + -1]` with `j` from 1, that term is the cell before `y`, so it lies in the input
declared before `y`. For an i64 sum, the exact `int32_t` block length then came from that
input's range: 2^31 − 1 terms for an `x` in `0..=1`, where `y`'s range allows one, so the
block could overflow. The emitter now names the input by the first cell a load reads, with
every axis at 0 and every sum variable at its lower bound. Admitted reads stay inside their
own input at every point, so that cell names the right one. A regression test shows the
one-term blocks, and it fails without the fix.

**Verification.**
- `tests/test_scale_abi2.py`: 16 tests. All but the size test were written before the
  change and failed on it; the shifted-load test fails without the fix.
- Native runs of 15 programs through a harness that gives each input its own array. Each
  runs on good data, and with a bad value at the first and last cell of every input that a
  value of its type can fail, at 1 and 4 threads: 118 runs per build.
  - On Windows (clang), Application Control blocked some of these launches.
  - In WSL (gcc), all 118 ran in each of three builds (plain, TSan and ASan+UBSan): 354 runs,
    all clean.
- The programs cover every emission path: the mixed u8/i8/i32 layer per cell and in
  parallel, the four-input i64 requantization, a 65,536-term u8 × i8 dot product split
  across threads, carry stencils, matmul, transpose tiles, streaming stores, i8 dense
  layers, and the shifted-load case.
- **The size test.** The 4096 → 11008 layer with u8 activations, i8 weights and an i32 bias
  matches the sampled reference natively, on Windows and in WSL, under both sanitizers.
- A two-input program of 2^31 cells in total builds with an `int64_t` status. Its run is not
  tested: 2 GiB of input is too large for the test machine's budget.
- The 98 related tests pass. Two older tests now expect the new behavior: inputs may pass
  the limit together, and inputs may mix storage types.
- The full suite (632 tests) has no new failures. The four unexplained failures also fail in
  3a's run. Every other failure has a known Windows cause; Application Control blocked 12
  launches.

**Not in 3b.** ABI 2 is not yet the default for single-type programs. Making it the default
needs the matched benchmarks rerun on it, and those runs are blocked on Windows today.

## Phase 3a: data up to 2^31 − 1 cells (2026-10-26)

The first part of phase 3 of `2026-10-25-ml-scale-cpu-core-design.md`. The kernel interface
is unchanged. Codegen stays `beryl-loop-c-v2`, and the generated C for every program admitted
before is byte-identical (13 checked against `9a8d7c9`).

**Limits.** These were 2^24, and are now 2^31 − 1:
- cells per tensor: each input, the producer and the output;
- input cells in total (lifted in 3b, whose ABI 2 has an `int64_t` status);
- terms per sum.

The total input limit keeps the status, the first bad index plus one, inside the
`int32_t` return value. Index arithmetic was already `int64_t`, and loop variables stay
`int32_t` per axis. The proof is by template, so admission and checking cost the same at
any size; the limit tests prove and emit a 2^31 − 1 cell copy in well under a second.

**Emission at the new sizes.** Programs past the old limits get two changes. Nothing below
those limits reaches either one.
- *Stepped counters.* A loop counter stepped by `k` is `int64_t` when one step past its last
  value could pass `INT32_MAX`; otherwise it stays `int32_t`. Two counters can do this: the
  64-cell blocks of the streaming loop, and the exact `int32_t` blocks of an i64 sum. Tiles
  cannot, because 16 rows of 2^27 cells already reach the limit.
- *The driver's buffers.* Above 1 GiB they come from `calloc`, and exit code 71 means
  allocation failed. Static arrays that large do not link on Windows, nor on Linux without
  `-mcmodel=medium`. Smaller buffers stay static.

**The sampled reference.** `reference.evaluate_cells(module, value_at, cells)` evaluates
only the chosen output cells.
- `value_at(i)` gives the input buffer's value at position `i`, so no input is ever
  materialized.
- Producer cells are computed on demand and cached, with the full reference's exact-integer
  and storage rules.
- Every value it reads must lie in its input's range. Since it sees only those values,
  there is no preflight.
- It agrees with `evaluate_source` on every cell of nine programs, including carry-free,
  i64, narrow-storage and per-cell-sum ones.

**The size test.** A 4096 → 11008 int8 dense layer, with weights stored `[out, in]`: 45
million weights, 2.7 times the old limit. The harness generates its inputs in place from a
hash that the test shares, and compares sampled outputs with the sampled reference, at 1
and 4 threads. The test also covers a bad last weight, and a 2^31 − 1 term i64 sum of one
cell run natively at values 0, 1 and 200, plus a bad value.

**Verification.**
- `tests/test_scale_large.py`: 12 tests. The limit tests fail on the old limits.
- The 128 related tests pass. Three older tests that checked the 2^24 limits (scale family,
  frontend and reduce family) now check one past the new limits.
- The full suite (616 tests) has no new failures. The three unexplained failures predate
  this work. Every other failure has a known Windows cause; Application Control blocked 35
  launches that day.
- TSan and ASan+UBSan in WSL are clean on 28 runs, at 1 and 4 threads:
  - the full int8 layer;
  - a 3000 × 1500 i32 layer, with bad values in each input;
  - the 2^31 − 1 term sum.

**Not in 3a**, still phase 3: one pointer per input (ABI v2), mixed storage types such as u8
activations with i8 weights, up to four inputs, and an `int64_t` status.

## Phase 2f: a cheaper check and better cell orders (2026-10-25)

Phase 1 of `2026-10-25-ml-scale-cpu-core-design.md`. Only the emitted C changes, so codegen
is now `beryl-loop-c-v2` (and `-parallel-v2`). Admission, semantic digests (13 checked) and
the checker are unchanged.

**The input check.**
- `(uint32_t)(v - lo) > hi - lo` holds exactly for the `v` outside `lo..hi`, when both
  are in i32. So one unsigned maximum per value decides a range, and the reduction
  vectorizes.
- The preflight, the per-chunk check, the per-input `beryl_check` and the fused sum check
  all use it now. The first-bad-index scan, which runs only on failure, is unchanged.
- A range that covers its whole storage type, whether i32 or narrow, has no check.
- Measured on one thread with AVX2: 4.0 → 2.9 µs on a 65,536-value sum, whose time with no
  check at all is 2.8 µs. Large inputs remain bound by reading the input twice. That is
  what the opt-in fused contract in the design addresses.

**Cell orders.** These are emission strategies, like row accumulation and streaming, so they
are on the "argued and tested, not checked" list. Every cell is a pure function of its
position and is written once, so any order that covers each cell once stores the same output.
- *Tiles.* When a load outside any sum moves more than one cell per column step (a
  transpose), output rows are computed in 16 × 16 tiles. Edge tiles are clamped, and work
  is split across threads by tile rows. 2048 × 2048 transpose: 34.4 → 9.0 ms in WSL with
  gcc. Tiles of 16 beat 8, 32 and 64.
- *Per-cell sums.* Row accumulation is chosen only when no load in the sum body is strided
  in the column variable. Weights stored `[out, in]`, as `torch.nn.Linear` stores them,
  are contiguous in the sum variable instead, so each cell keeps its own inner sum. On a
  1024 × 4096 int8 dense layer: 12.6 → 0.71 ms, with identical outputs. Matmul keeps row
  accumulation.

**Verification.**
- `tests/test_scale_check.py`: emitted checks, no check for full-type ranges, per-input
  checks, the fused accumulators, and native first-bad-index runs at each input's ends and
  at the type extremes, at 1 and 4 threads.
- `tests/test_scale_tiles.py`: when tiles and per-cell sums apply, and native agreement on
  edge tiles, a lone partial tile, and parallel sizes.
- The 129 related tests pass.
- TSan and ASan+UBSan are clean on 264 WSL runs: the new paths plus the storage and shift
  sets.

**Benchmarks** are in `docs/reviews/2026-10-25-matched-benchmarks.md`, section "AVX2 and
the first speed fixes".

## Phase 2e: u8, i8 and i16 storage (2026-10-25)

**Language.**
- Inputs and the output may declare `u8` (0..255), `i8` (-128..127) or `i16`
  (-32768..32767): `input x: u8[H,W] in 0..=255;`, `output y: i8[...] = ...;`.
- These are storage types only. Every scalar node is exact in i32, or in the declared type
  of an i64 equation, as before; the narrow type constrains what is stored.
- An input's declared range must lie inside its type (`INVALID_RANGE`).
- Every input of a program has one storage type, because the buffer is one array; mixed
  types are `UNSUPPORTED_PROFILE`.
- A `let` stays i32 or i64; a narrow `let` is `UNSUPPORTED_TYPE`.
- Like i64 equations, narrow storage is `scale-v1` only; the 256-cell families store i32.

**Meaning.**
- The reference evaluates an output in its arithmetic type, then requires each value to
  fit its storage type (`EVALUATION_U8` and so on).
- Input and initial-output values outside their storage types are boundary errors
  (`BOUNDARY_U8`).
- An input value inside its type but outside its declared range is the usual
  precondition failure, with the first bad index.
- The semantic record gains `storage: {input, output}` only when a narrow type appears.
  So digests of existing programs are unchanged (13 checked).

**Proof.** The checker computes the output template's interval in the arithmetic type as
before. For a narrow output it also requires that interval to lie inside the storage type,
or refuses with `ARITHMETIC_OVERFLOW`, naming the reachable range and suggesting `clamp`.
Producers and interior output nodes may exceed the storage type: only the stored value must
fit.

**Emission.**
- The kernel takes `const uint8_t *`, `int8_t *` or `int16_t *` arrays. Loads promote to
  `int`, so the arithmetic text is unchanged.
- A stored value was proved to fit, so the conversion on store is exact.
- For a narrow input, a range bound at the type's limit is left out of the preflight,
  since no stored value can fail it. A full-range `u8` input has no check at all.
- The streaming copy moves `int32_t` cells, so narrow outputs keep ordinary stores.
- The standalone driver parses each token as before, then refuses any outside the input
  type with exit 65 instead of wrapping it. Without this, 300 would wrap to 44, a value
  inside a `16..=235` range.
- C for existing programs is byte-identical to the previous commit (13 programs: the
  min/max, shift and full-range i32 ones included).

**Verification** (`tests/test_scale_storage.py`):
- admission and routing of `u8`, `i8` and `i16`, including small programs;
- ranges outside the type, mixed input types, and narrow `let`s;
- storage in the identity;
- reference rounding and the refusal of values that do not fit;
- boundaries;
- proofs of a u8 blur, an i8 dense layer and an i16 Q15 gain;
- refusal of each when its output may not fit;
- direct-v1 and carry-v1 plans against the reference at the range ends;
- the narrow kernel signature, and the elided full-range check;
- 48 native runs at 1 and 4 threads;
- driver runs that refuse out-of-type tokens (exit 65) and out-of-range values (exit 66).

ThreadSanitizer and ASan+UBSan are clean on 68 WSL runs at 1 and 8 threads, across carry,
parallel and serial plans.

**Next for demo A.** Activations and weights now take one storage type, i8 or u8. Mixing
u8 activations with i8 weights needs per-input buffers in the kernel ABI.

## Phase 2d: right shifts and rounding (2026-10-25)

**Language.**
- `shr(x, k)` is exactly `floor(x / 2^k)`.
- `shr_round(x, k)` is exactly `floor(x / 2^k + 1/2)`: halves round up, as in Arm's
  rounding shift instructions.
- `k` is an integer literal, possibly parenthesized: 0..63 for `shr`, 1..63 for
  `shr_round`.
- The parser refuses:
  - a shift amount that is not a literal (`SYNTAX_ERROR`);
  - an amount out of range (`INVALID_EXPRESSION`);
  - wrong argument counts;
  - shifts in an index.
- There is no left shift, because `x * 2^k` already says it and is checked as a product.

Both are `BinaryExpression`s whose right operand is the literal, so the kind and the
amount are part of the semantic identity. As with min and max, small programs that use
them are `scale-v1`.

**Proof.** Both functions are nondecreasing in `x`, so the checker maps the operand's
interval ends through them:
- `shr` maps each end to `end // 2^k`;
- `shr_round` maps each end to `(2·end + 2^k) // 2^(k+1)`.

The result can never overflow, and the operand is checked as before. The narrower bounds
flow into sums and into i32 equations that read i64 ones. That is what makes int8
requantization provable: an i64 accumulator times a fixed-point multiplier, shifted by 40
with `shr_round`, fits an i32 output that clamps it to int8.

**Plans and emission.**
- Plans gain `('shr', a, ('const', k))` and `('shr_round', a, ('const', k))`, matched
  structurally. Swapping the kinds, or changing the amount, is a `STRUCTURAL_MISMATCH`.
- The emitter calls `static inline` helpers `beryl_shr_i32`, `beryl_shr_round_i32` and
  the i64 forms. They shift only nonnegative values, and only by less than the width; a
  negative `a` uses `~(~a >> k)`. So no shift is undefined or implementation-defined.
- `shr_round` is emitted as `shr(a, k) + (shr(a, k-1) & 1)`, which cannot overflow. The
  runtime uses the same identity. The reference and the checker use the floor-division
  definition, so a mistake in either form would show up as a disagreement.
- The helpers are emitted only when a plan uses them. C for existing programs, the
  min/max ones included, is byte-identical to the previous commit (nine programs).

**Verification** (`tests/test_scale_shift.py`):
- syntax: argument counts, literal amounts, the amount ranges, and indices;
- routing to `scale-v1`, and the identity of the kind and the amount;
- floor and round-half-up meanings on hand-computed negative and positive cases;
- the requantize reference;
- longer sums of shifted terms;
- that operands are still checked;
- that the requantized i64 producer fits an i32 output, and the unshifted one does not;
- rejection of changed kinds and amounts;
- direct-v1 and carry-v1 plans against the reference at the range ends, including
  amounts of 31, 32 and 63 over the full i32 range in both i32 and i64 equations;
- a 240-mutant fuzz, in which the mutator also swaps shr and shr_round;
- 56 native runs at 1 and 4 threads.

ThreadSanitizer and ASan+UBSan, which checks shift amounts and operands, are clean on 64
WSL runs at 1 and 8 threads, including all-minimum inputs (-2147483648).

## Phase 2c: min, max and clamp (2026-10-25)

**Language.** `min(a, b)` and `max(a, b)` are scalar nodes with the exact integer meaning.
`clamp(x, lo, hi)` is defined as exactly `min(max(x, lo), hi)`, the way `a - b` is defined
as `a + (-1)*b`. So clamp has no node of its own, and writing either form gives the same
semantic identity. The parser refuses:
- wrong argument counts (`SYNTAX_ERROR`);
- literal clamp bounds with `lo > hi` (`INVALID_EXPRESSION`);
- min or max in an index.

The nodes are `BinaryExpression`s with operator `min` or `max`, and they appear in the
profile as `['min', a, b]`. The 256-cell families accept only `+` and `*`, so a small
program using them is `scale-v1`. Existing programs keep their identities, because their
profiles contain no min or max.

**Proof.** The interval of `min(a, b)` is `(min(a.lo, b.lo), min(a.hi, b.hi))`, and `max`
works the same way with `max`. Neither can leave the type of its operands, and the
operands are checked as before. The tighter bounds flow into sums. A sum of
`min(x[0,k], 255)` over a 0..1023 input admits 8,421,504 terms in i32, where `x[0,k]`
alone admits 2,099,202.

**Plans and emission.**
- Plans gain `('min', a, b)` and `('max', a, b)`.
- The checker matches them structurally, like `add`/`mul`, so a plan that swaps min and max
  is a `STRUCTURAL_MISMATCH`.
- The emitter calls `static inline` `beryl_min_i32`, `beryl_max_i32` and the i64 forms.
  They are emitted only when the plan uses them, so the C of every existing program is
  byte-identical (checked on box, sum, int8 dot and signed box).
- carry-v1, exact int32 blocks and the fused input check handle the new nodes.

**Verification** (`tests/test_scale_minmax.py`):
- syntax: argument counts, clamp's meaning, and inverted clamp bounds;
- routing of small programs to `scale-v1`;
- the overflow proof with capped and floored terms;
- that operands are still checked;
- the min/max swap;
- the reference meaning on hand-computed cases;
- direct-v1 and carry-v1 plans against the reference at the range ends;
- a 240-mutant fuzz, in which the mutator now also swaps min and max;
- 52 native runs at 1 and 4 threads. They cover ReLU on an int8 dot, a clamped signed
  filter, capped sums of 2.2M terms with the fused check, and i64 min/max over the full
  i32 input range.

ThreadSanitizer and ASan+UBSan are clean on 72 WSL runs at 1 and 8 threads.

## Phase 2b: per-input ranges and the fused input check (2026-10-25)

**Per-input ranges.** A `scale-v1` input may declare any range inside i32, signed
included, per input (`input w: i32[1,n] in -128..=127`).
- The range is part of the profile, so it is part of the semantic identity.
- The frontend refuses ranges outside i32 (`INVALID_RANGE`).
- The checker bounds each read by its own input's range. The overflow refusal names the
  range when every input shares one, and says "the declared input ranges" otherwise.
- The reference and the loop-plan runtime check each input's buffer segment against its own
  range, and report the first bad index over the whole buffer.

In the emitter:
- **Shared range:** programs whose inputs share one range keep the inline checks, and their
  C is byte-identical to before.
- **Mixed ranges:** the check is a `beryl_check(input, from, to)` helper that loops over each
  input's segment with that input's bounds; the first-bad scan does the same.
- **Exact int32 blocks:** they use each load's input range. A load's constant term is its
  lowest index, since indices only add nonnegative offsets, so it names the input.

The 256-cell families keep `0..=1023`; a small program with another range is `scale-v1`.

**Fused input check.** In a single-cell sum, consider each load `input[c + k]` over the whole
sum range. When those ranges together cover every input index, each chunk of the sum ORs a
range check over exactly the values it adds:
- this applies to sum, and to dot reading x then y;
- the output is written only after every chunk is in;
- on any bad value, the existing scan reports the first bad index.

So the contract is unchanged, and the input is read once instead of twice. Sums that read
only part of the input keep the separate check. Measured effect (single thread):

| kernel | before | after | C |
|---|---|---|---|
| sum, 4M values | 1.90 ms | 1.31 ms | 1.34 ms |
| dot, 2 × 2.1M values | 1.88 ms | 0.91 ms | 1.09 ms |

Full matched numbers are in `docs/reviews/2026-10-25-matched-benchmarks.md`.

**Verification.**
- `tests/test_scale_ranges.py`:
  - admission, identity and i32 bounds;
  - the overflow proof per range, including signed squares at ±46,340;
  - a per-input check order;
  - a 240-mutant fuzz checked at the low and high range ends;
  - 60 native runs: low, high and random values, and bad values in the first and last input,
    at 1 and 4 threads.
- `tests/test_scale_fused.py`: whether the check is fused or kept, and 30 native runs with
  bad values at the first, middle and last index.
- ThreadSanitizer and ASan+UBSan clean on 48 fused runs and 60 range runs in WSL.
- The candidate checker now samples inside each declared range, and refuses to count a
  sample that fails the input check.

## Phase 2: i64 equations (2026-10-24)

Phase 2 adds element types for equations. Per-input intervals are not done yet.

**Syntax.** `let t: i64[...]` and `output o: i64[...]`. An equation without a type is i32, so
existing programs keep their bytes, profiles and semantic digests. Writing `: i32` explicitly gives
the same digest. Inputs stay i32. i64 is admitted only in scale-v1: the 256-cell families emit
i32 code, so an i64 program of any size is scale-v1.

**Semantics.**
- Each scalar node must be exact in its own equation's type.
- An i32 equation reading an i64 producer must still fit i32.
- The reference evaluator checks this per node (`EVALUATION_I64` / `EVALUATION_I32`). Output
  boundary values must fit the output's type.
- A program with an i64 equation has its own semantic version, `scale-i64-v1`. Its semantic
  record names the element types, so the same text with i32 gets a different identity.

**Proof.** The template checker's interval analysis bounds every node by its equation's type, and
bounds every sum by that type's maximum (`terms * max|term|`). Producer reads are checked against
the reading equation's type, which catches narrowing. When an i32 sum would overflow, the refusal
says how many terms fit and suggests declaring the equation i64.

**Emission.** A program with any i64 equation computes in `int64_t`. Loads and literals are
widened; accumulators, the carry ring and the pool's partials are `int64_t`. Every node is proved
to fit its own type, so i32 nodes keep their exact values. i64 outputs are `int64_t` arrays, and
the driver prints them with a 64-bit formatter. Streaming stores remain i32-only.

**Exact int32 blocks.** Widening every term made the i64 sum 2x slower than the i32 one, and
slower than C. Instead, when every node of a sum's body fits i32, the emitter adds runs of
`I32_MAX // max|term|` terms in `int32_t` and widens once per run:

- about 2.1 million terms for `sum`;
- 2,052 for `dot`.

Any run that short sums exactly, by the same interval argument as the proof. The emitter
recomputes these intervals over the plan, which the checker has proved equal to the source
template. This is an emitter argument, like the parallel split.

**Results** (Ryzen 3 3100, against single-threaded C with i64 outputs; beryl uses all cores):

| kernel | s | m | l |
|---|---|---|---|
| sum | 0.59x | 0.46x | 0.72x |
| dot | 0.95x | 0.45x | 0.77x |

These are beryl's time divided by C's; lower is faster.

**Verification.**
- `tests/test_scale_i64.py` (13 tests) covers:
  - parsing and identity;
  - refusals: narrowing, an i32 node inside an i64 program, past i64;
  - reference agreement;
  - the carry ring cost;
  - a mutation fuzz;
  - native agreement for 9 programs.
- The bench drafts for sum and dot now declare i64, matching the C baselines' 64-bit outputs.
- Sanitizers in WSL are clean: TSan and ASan+UBSan on 7 i64 kernels × 3 inputs × 1 and 8
  threads, 84 runs.
- Executables in the temp folder are blocked by Application Control on this host, so the native
  test skips there. The same comparison was run from `.local` with 0 mismatches.
