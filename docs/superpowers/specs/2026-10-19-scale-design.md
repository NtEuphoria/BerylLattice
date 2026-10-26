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
