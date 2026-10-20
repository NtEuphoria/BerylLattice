# Proof-boundary review: 8eb9e4d, c9ab0e4, ef8cc0a (+ uncommitted reduce-v1)

Reviewer: independent, read-only. Committed code was reviewed at `ef8cc0a` from git objects, not
from the working tree. The working tree had uncommitted reduce-v1 edits while this review ran.
To test the committed code, every experiment loaded `axiom/src` and `axiom/tests` from
`git show <rev>:...` through an in-memory importer. A few temporary corpus files were written to
the session scratchpad only.

## Summary (ranked)

| # | Severity | Status | Finding |
|---|----------|--------|---------|
| 1 | Medium (availability / DoS) | CONFIRMED (scaling measured) | Window plan generation has no bound before `plan_operations` is enforced. inline-v1 grows as H*W x reads x producer size. |
| 2 | Medium (functional) | CONFIRMED | A valid family kernel whose inline-v1 exceeds `plan_operations` stops ranked selection with no artifact, although rows-v1 and materialize-v1 fit. |
| 3 | Low (semantics wording) | CONFIRMED by reading | `a - b` is defined as `a + (-1)*b`. When `b == INT_MIN`, this overflows where true subtraction would not, so such sources are rejected. Conservative and consistent across checker, reference and backends. |
| 4 | Info | CONFIRMED | `window_explain` changes only the spans and messages of rejections. Codes, admissions, semantic digests and canonical plan bytes are unchanged. |
| 5 | Info | checked | No soundness defect found in admission, checker or reference agreement, compact-hint correspondence, or the fast preflight (details below). |

None of these is a soundness bug: no wrong output, no out-of-bounds access, no unchecked overflow.

## 1. Plan generation has no bound (DoS) - CONFIRMED

- `window_planner.make_window_plan` (axiom/src/axiom/window_planner.py:138-142, inline-v1) builds
  the whole operation list in memory. The limit is applied only later, in
  `context.candidate(plan)` -> `validate_plan` (compilation_selection.py:197-200, codec.py).
- inline-v1 re-lowers the producer for every distinct output read of every output cell. The memo
  works per evaluation only (window_planner.py:90-117). Cost is about H*W x (<=81 read positions)
  x (distinct producer subterms).
- Measured at ef8cc0a. The input is a 9x9 box (`x: i32[H+8,W+8]`, H=W=8, 81 balanced reads of
  `p[r+i,c+j]`). The producer is a balanced sum of n distinct terms `x[r,c]*k`:

  | n | source bytes | inline ops | generation time |
  |---|--------------|------------|-----------------|
  | 25 | 1653 | 264,409 | 1.18 s |
  | 50 | 2003 | 523,634 | 2.29 s |
  | 100 | 2705 | 1,042,084 | 4.79 s |

  Growth is linear in n. The 65,536-byte source cap allows roughly 4,000 terms within the depth-32
  limit, which means tens of millions of `Operation` objects: minutes of CPU and several GB of RAM
  before `OPERATION_LIMIT` fires.
- Exposure: `playground_service._run` -> `select_plan` and `prepare_compiled_demo` ->
  `compile_wasm_source` both run on request source (playground_service.py:211-240, 287-295).
- The uncommitted reduce-v1 path reuses `make_window_plan`, so sums and gathers inherit this.
- Fix: count operations in `emit` and fail as soon as
  `len(operations) >= limits.plan_operations` (pass `limits` into `make_window_plan`), or bound
  H*W*reads*producer_nodes at admission.

## 2. One oversized candidate stops the whole portfolio - CONFIRMED

- Source: the 9x9 box above with producer `(x[r,c]+1)*(x[r,c]+2)`, H=W=8, 256 input cells,
  admitted as window-stencil-v1.
- Plan sizes: inline-v1 25,922 ops (above 20,000), rows-v1 11,650, materialize-v1 11,650.
- `compile_native_source(src)` returned no artifact. Attempts: inline-v1 `unknown OPERATION_LIMIT`.
  rows-v1 and materialize-v1 were never examined.
- Cause: compilation_selection.py:206-212 treats every resource-limit `DecodeError` other than
  `INVALID_PLAN` as policy-stopping. That is safe, but for the window family inline-v1 is always the
  largest candidate. Every moderately sized admitted kernel therefore becomes uncompilable, and
  admission promises more than compilation delivers.
- Options: give generators a structural size precheck, or mark size-limited candidates
  STRUCTURALLY_REJECTED (with an honest `portfolio_optimal=False`). Otherwise, make admission reject
  kernels whose smallest candidate exceeds the limits.

## 3. Minus desugar - low

- frontend.py:240-255 rewrites `a - b` as `a + ((-1) * b)`. A minus inside an index or shape is a
  `SYNTAX_ERROR` at the operator.
- Before ef8cc0a, every binary-minus source was already a `SYNTAX_ERROR`. The desugar therefore
  cannot change the admission of any previously admitted source, and cannot produce the canonical
  profile, which has no `-1` literal.
- `a - b` and `a + -1*b` share a profile, so they share a semantic digest. This is intended, and the
  semantics are identical.
- Edge case: if `b` can reach INT_MIN, `(-1)*b` overflows even when `a - b` would fit. Example:
  `(p[r,c]*0 + -1) - -2147483648`. The checker reports `ARITHMETIC_OVERFLOW` and the reference
  reports `EVALUATION_I32`, so they agree. It is only a definitional difference; document it in
  docs/window-stencils.md.
- The `-1` literal reuses the operator's span. The extra 2 nodes per minus count toward node and
  depth quotas (stricter, which is fine).

## 4. window_explain and canonical identity - CONFIRMED unchanged

- window_explain.py only builds messages. frontend.py calls it only after admission has been
  decided (frontend.py:552-554 counts, 567-570 profile). It never raises anything except through
  `_fail('UNSUPPORTED_PROFILE', ...)`. Inspection found no IndexError or AttributeError path: counts
  are already (2,1,1,1) and every walk is type-guarded.
- Differential run: 3,005 mutated canonical sources without minus, evaluated at `8eb9e4d~1`,
  `ccdb0c9` and `ef8cc0a`:
  - `ccdb0c9` vs `ef8cc0a`: identical OK/ERR outcomes and codes, identical semantic digests.
    35 rejections differ only in span offset (expected from the explainer). 0 crashes.
  - `8eb9e4d~1` vs `ef8cc0a`: all 30 canonical admissions have identical semantic digests and
    identical plan bytes (sha256 of inline-v1, rows2-v1 and materialize-v1). The only difference is
    8 sources newly admitted as window-stencil-v1, which is the intended family growth.

## 5. Questions 1-3: no defect found (evidence)

### Q1. Admission, checker and reference agreement
- `window_shape` (window_family.py:56-80) requires all of the following:
  - input i32 with interval [0,1023];
  - input dimensions `shapeN[+k]` with k in 1..8;
  - producer axes `0..shapeN[+k]`;
  - output axes exactly `0..shape0` and `0..shape1`;
  - producer reads only `input0[axis0+i, axis1+j]` and output reads only `producer0[...]`, with
    offsets 0..8 and at least one read each.
- Bounds were already proved by `_validate_scalar` against each tensor's declared extent
  (frontend.py:421-444). The checker re-bounds each read by its own tensor extent (checker.py:211-214).
- The 256-cell cap is on the input (window_family.py:86). Producer and output are no larger.
- Axis names that shadow shape names resolve the same way in all three places: frontend `_interval`
  checks axes first, reference does `scalars.update(axes)`, and the checker overrides `env`.
- checker.py:363 hard-codes `{'H','W'}` in env. This is harmless because family reads never contain
  shape names (`_offset` requires `axis` or `axis+k`). It is still fragile; build env from
  `module.shapes`.
- Overflow: the checker interval-checks every source node it reaches and every plan add/mul,
  including dead operations (checker.py:103-125, 385-387). `VALID` requires `not inconclusive`. Every
  producer cell has the same expression and input interval, so producer cells the output never reads
  (inline-v1 and rows-v1 skip them, while the reference evaluates the whole producer domain) cannot
  overflow when any read cell is proved safe. The checker and reference therefore cannot disagree on
  overflow.
- Differential fuzz: 250 random family programs with random a, b, pa, pb, H, W, and expressions
  using +, *, - and literals up to 65536. For each, all 3 plans were checked; eligible plans were run
  with `execute_plan` against `evaluate_source` on zeros, 1023s, random input, and a bad-index input.
  Results: 606 VALID, 126 ARITHMETIC_OVERFLOW, 18 INCONCLUSIVE. 0 disagreements and 0
  planner/checker mismatches.

### Q2. Untrusted compact hints
- Correspondence (bounded_loop_correspondence.py:90-150, 179-189):
  - every index intermediate is checked to fit i32 at every executed iteration;
  - each final index is bounds-checked against the actual arena (now `kernel.input_count`);
  - the full stream (opcode, dst, operands, index, value, plus capacity and length) is matched.
- Lexical scoping in the expansion matches C and Wasm block scoping. The codec forbids shadowing an
  active name. Parity uses `& 1` on uint32, which equals Python's `% 2`.
- Widening the hint height and width to <=256 with H*W<=256 (bounded_loop_codec.py:123-126) is safe
  because specialization binds the exact kernel H and W (correspondence.py:33-38), and loop bounds
  were already 0..256.
- Zero-trip loops are skipped in C. Every intermediate goes through int64 before narrowing
  (bounded_loop_c.py:243-261).
- `make_window_loop_program` raising ValueError becomes `HINT_UNAVAILABLE` and falls back to finite
  code (source_compilation.py:46-49). Other exception types would propagate as a crash, not a wrong
  result. Consider catching `Exception` there.
- Fuzz: 606 of 606 hints expanded and matched. For 120 kernels, compact Wasm and finite Wasm, run on
  Node v24, produced identical full 64 KiB memory and matched the reference on all four input
  patterns, including the bad-input cases.

### Q3. Fast preflight
- native_codegen.py:174-185 OR-reduces validity over every input cell and rescans to return the
  first bad index + 1. No scratch is declared and no output is written before it. This matches the
  runtime (runtime.py:76-79) and the reference (reference.py:109-113).
- The Wasm fuzz confirmed that the status, untouched input and untouched initial output on
  rejection all match the reference.
- `restrict` on input and output is sound under the documented disjoint-ownership contract. The
  driver uses distinct arrays.
- Canonical finite C keeps its legacy bytes: disjoint and reduction are both False when
  profile != WINDOW (native_codegen.py:115-116).

### Other notes (info)
- Canonical-only consumers that still use `(H+1)(W+1)` are all behind `require_canonical`:
  core_emit, core_capsule.decode_case, core_runner and evidence. core_observe is reached only from
  core paths. `source_profiles` (v2) independently admits only the canonical profile. Nothing leaks.
- `playground_web/benchmarks.js:62-69` still assumes `(h+1)*(w+1)` inputs. Check whether it is
  reachable for family examples.
- At ef8cc0a, the HEAD test modules for window_family, window_compact, window_guide, frontend,
  reference and bounded_loop_* pass (65 tests). The only 2 errors come from the in-memory importer
  (no on-disk `__file__` and `inspect.getsource`), not from the code.

## Uncommitted reduce-v1 (brief, working tree at review time)

Spot checks:
- `tests.test_reduce_family` passes (6 tests).
- A matmul (`x: i32[H,5]`, `y: i32[5,W]`, `p = sum(k in 0..5: x[r,k]*y[k,c])`) passes all 3 plans
  VALID. The runtime equals the reference on random and bad inputs, and the reference equals a
  hand-computed matmul.

Findings:
- Buffer layout: the checker (`all_input_shapes` bases), the planner (`bases`) and the reference
  (declaration-order offsets plus a coverage check) all use declaration-order concatenation.
  `input_shapes` was added to the checker identity fields. The preflight covers the summed
  `input_count`. Consistent.
- `parse_sum`: pure parser sugar that expands to a balanced `+` tree. Copies are counted against
  `expression_nodes`; the discarded original body is also counted, which is conservative. The
  variable may not equal a shape, an active axis or an outer sum variable. Only `NameReference` is
  substituted, so tensor names are unaffected.
- `window_loop_planner` refuses REDUCE_PROFILE, so compact hints fall back to finite code. If it is
  extended later, its `read_input` must use per-input bases and strides, not `kernel.input_cols`.
- Finding 1 (plan generation has no bound) applies directly: nested sums with gathers multiply the
  inline-v1 size.
- The two-input interval relies on `reduce_shape` requiring [0,1023] for every input, while the
  kernel stores only `inputs[0].input_interval`. That is fine today, but assert it if per-input
  intervals are ever allowed.
- Stray untracked files `axiom/0` and `axiom/0),+` in the working tree look like accidental shell
  redirections.

## Follow-up (2026-10-19, same branch)

| # | Action |
|---|---|
| 1 | Fixed. `make_plan`/`make_window_plan` take `max_operations`. Every selection path passes `limits.plan_operations`, and generation stops at the quota with the same `OPERATION_LIMIT` code. Test: `test_reduce_family.test_oversized_plans_stop_at_the_operation_limit`, where the reviewer's 9x9 box over a 100-term producer now fails in under a second. |
| 2 | Open: an owner decision. Skipping size-limited candidates changes the selection policy (`portfolio_optimal`, policy identity). |
| 3 | Documented in `axiom/docs/window-stencils.md`. |
| Hardening | Open: build the checker's shape env from `module.shapes`; widen the hint-planner fallback beyond `ValueError`; fix `playground_web/benchmarks.js` input counts for family kernels. |
| Stray files | Removed. |
