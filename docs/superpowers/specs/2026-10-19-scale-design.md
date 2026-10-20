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
  (phase 2).
- **matmul l is slower than C.** Its 256-term sum is expanded into one 256-product expression per
  output, while C runs a cache-friendly i-k-j loop. Loop-order and tiling schedules (phase 3) are
  the fix.

## Roadmap

| Phase | Adds | Unlocks |
|---|---|---|
| 1 | template proofs, loop plans, native C loops, symbolic sums | m/l tiers of stencils, polymap, transpose, sum, matmul |
| 2 | element types (`i64` equations and outputs), per-input intervals | dot, large sums, any input range |
| 3 | schedules with proof rules: materialized producer, rolling rows, tiling | separable stencils without recomputation, cache-blocked matmul |
| 4 | loop plans in Wasm and the Python runtime; playground at scale | interactive large programs |
| 5 | language: `max`/`min`, comparisons and `select`, strided indices, several equations | maxpool, life, scan |

Every phase that changes what is admitted or how plans are trusted gets an independent review
before it is relied on.
