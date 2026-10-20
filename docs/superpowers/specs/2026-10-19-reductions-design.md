# Reductions and a second input (reduce-v1)

Status: implemented on `feat/bench-native`. Follows item "reductions with a second input" of
`docs/reviews/2026-10-19-gaps-and-improvement-plan.md`.

## Goal

Admit `sum`, `dot`, `matmul`, transposes and other gathers within the existing 256-cell bound,
without changing the plan format, the checker's proof method, any backend, or the identity of any
program admitted today.

## Language

**`sum(k in L..U: e)`** is a scalar expression. `L` and `U` are integer literals with
`1 <= U - L <= 256`. It is defined as exactly a balanced `+` tree over the terms `e[k := L]` ..
`e[k := U-1]`:

    tree(lo, hi) = term(lo)                              if hi - lo == 1
                 = tree(lo, mid) + tree(mid, hi)         mid = (lo + hi) // 2

Association is part of the semantics (every `+` is an i32-checked node), so this definition is
fixed. A balanced tree keeps the depth at `depth(e) + ceil(log2(U - L))`, within the parser's
depth-32 limit for 256 terms; a left fold would not be. `k` may appear anywhere in `e`, including
index and scalar positions, and is replaced by an integer literal. It must not reuse a shape name,
an axis of the enclosing equation, or an enclosing `sum` variable. As with `-`, the expansion
happens in the parser and every later stage sees ordinary `+`, `*`, literal and read nodes; a `sum`
and its written-out balanced form are the same program (same semantic digest).

**A second input.** A program may declare one or two inputs. The runtime input buffer is their
row-major contents concatenated in declaration order; `first_bad_index` is an offset in that
buffer.

## Family `reduce-v1`

Admitted when the program is neither the canonical stencil nor a window stencil (both keep their
admission and identities) and:

| Part | Rule |
|---|---|
| Shapes | exactly two literal shapes |
| Inputs | one or two, `i32`, 2-D, `in 0..=1023`; each dimension a literal, a shape, or shape + k (1..8) |
| Producer | one, axes `0..shape0+pa`, `0..shape1+pb` (0..8); reads only inputs; each index is an axis, axis + k (k >= 0), or a literal, in any position |
| Output | axes exactly `0..H`, `0..W`; reads only the producer, index i is `axis_i` or `axis_i + k` (0..8) |
| Size | at most 256 input cells in total |

Every read is already bounds-checked by frontend validation. The semantic record adds
`input_shapes` and `input_layout: declaration-order-concatenation` under semantics version
`reduce-i32-v1`.

## Implementation

| Stage | Change |
|---|---|
| Parser | `sum` expansion through the existing node/depth accounting |
| Admission | `reduce_family.py` recognizer, tried after the window recognizer |
| Model | `AdmittedKernel.input_shapes`; `input_count` totals all inputs |
| Checker | maps each input name to its base offset and extent (single-input kernels unchanged) |
| Reference | reads every input from its slice of the buffer, dimensions from its own AST evaluation |
| Planner | window plans (`inline-v1`, `rows-v1`, `materialize-v1`) with per-input base offsets |
| Native/Wasm | unchanged: compact hints are unavailable for this family, so the finite path is used |

## Results

All four `s`-tier kernels are admitted, all three plans check `VALID`, and execution matches the
reference evaluator and the benchmark oracle checksums.

Finite C for reduce-v1 uses the window family's contract: a branch-free OR-reduction input check
(the first bad index is recovered only on rejection) and `restrict` parameters. The canonical
stencil keeps its published bytes. Same-session medians (ns, `hash` and `max` patterns, 5-7 runs
each):

| Kernel | axiom-native before | axiom-native | C | native / C |
|---|---|---|---|---|
| sum (256) | 66 | 35 | 56 | 0.63 |
| dot (2x128) | 80 | 49 | 58 | 0.84 |
| matmul (8x8x8) | 172 | 152 | 343 | 0.44 |
| transpose (16x16) | 122 | 93 | 98 | 0.95 |

Unlike the C baselines, every axiom-native call validates all 256 inputs. Earlier Rust medians were
sum 53, dot 65, matmul 384 and transpose 253; Rust could not be rebuilt this session (Application
Control). Good and bad inputs (first, middle and last cell, including the second input) give the
same status and outputs as the reference evaluator. The kernels use the finite (unrolled) path,
because compact hints do not cover this family yet. The `m`
and `l` tiers are refused (`INVALID_RANGE` for over 256 terms, or over 256 input cells).

## Not in scope

`max`, comparisons, conditionals, strided indices, i64 accumulators, and more than 256 input cells.
