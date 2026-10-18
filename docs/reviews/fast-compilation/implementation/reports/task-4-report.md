# Task 4 — bounded structured hints and correspondence

Status: DONE_WITH_CONCERNS (independent review and backend integration remain coordinator gates).

## Delivered

Four new modules only: `bounded_loop_model.py`, `bounded_loop_codec.py`, `bounded_loop_planner.py`, `bounded_loop_correspondence.py`. Existing `planner.py` and all existing compiler modules remain unchanged by this task. Two new test modules and a frozen 2,865-stream corpus cover all 955 admitted shapes and all three schedules.

The immutable format is `beryl-bounded-loop-v1`, separate from scalable v2. It contains literal unit-step lexical `Loop` records and seven existing `Primitive` opcodes. Scalar names cannot shadow active scalar or loop bindings; operands reference prior definitions in the current or enclosing lexical scope. Each iteration receives fresh dense finite SSA identities. Loop-local definitions never escape. A hoisted constant is retained once.

The current two-row order is stage rows 0 and 1, then consume r and stage r+2, followed by the final consuming row. Its representation uses a loop over r in `[0,h-1)` plus a final consume; it needs no conditional.

`IndexExpr(constant, terms)` evaluates terms strictly in tuple order. Each `IndexTerm(coefficient, variable, offset, modulo2)` evaluates variable+offset, optional nonnegative mathematical modulo two, coefficient multiplication, and accumulator addition. Every intermediate is checked signed-i32; final indexes must be nonnegative and within the actual specialized arena. In C/Wasm, parity must use `& 1`, or another mathematically equivalent nonnegative modulo, because C signed `% 2` differs for negative components. Algebraic regrouping is not the format semantics.

Example: `IndexExpr(1, (IndexTerm(stride, 'r', 1, True), IndexTerm(1, 'c')))` denotes the ordered evaluation of `1 + stride*((r+1) mod 2) + c`.

## API and ownership

- `make_loop_program(kernel, schedule) -> LoopProgram` is an untrusted candidate generator.
- `encode_loop_program(program, hint_limits=HintLimits()) -> bytes` and `decode_loop_program(bytes, hint_limits=HintLimits()) -> LoopProgram` validate bounded records/bytes.
- `expand_loop_program(kernel, program, limits, hint_limits=HintLimits()) -> Plan` expands without semantic checking.
- `validate_loop_correspondence(kernel, actual_plan, loop_bytes, limits, hint_limits=HintLimits()) -> LoopCorrespondence` compares the complete executable operation stream, exact scratch reservation, and source/shape specialization.
- `evaluate_index(expr, variables, charge)` documents and implements the precise already-validated index evaluation contract.

`LoopCorrespondence.plan` retains the exact supplied Plan object. Other fields: program, expanded_plan, exact hint_bytes, SHA-256 hint_digest, canonical finite plan_digest, raw source_digest, semantic_digest, expanded_operations, work_steps, and correspondence version. Finite labels and origins are validated metadata but are excluded from executable correspondence comparisons. Structured labels are also metadata. Exact raw hint bytes, including whitespace, are bound separately from the decoded program.

No result has an eligibility field. The coordinator must separately require its owned complete successful finite check. The APIs here consume its freshly owned admitted kernel; they are not public admission bypasses or semantic proof APIs. A caller-supplied AdmittedKernel is not authority. Invalid hints raise HintError with a stable category. Existing finite structural validation may raise the existing DecodeError; the coordinator should catch both for optional-hint fallback. Neither resets finite/semantic quotas.

## Limits and measured fit

HintLimits fixed maxima are 65,536 encoded bytes, 4,096 syntax nodes, nesting depth 16, and 100,000 expansion work steps. Callers can lower these ceilings but cannot raise them. Existing finite plan operation and byte limits also apply. Literal loop bounds are exact integers from 0 through 256. The program must retain admitted positive dimensions and the 256-input boundary.

Before expansion, a saturating recursive syntax-sized cost calculation bounds each loop visit, iteration binding/removal, primitive, scalar operand lookup/definition/removal, and index evaluation step. Empty bodies and zero-trip leaves still charge enclosing traversal. Independent per-step charging enforces the same limit during expansion. Expanded operation count is separately prechecked and enforced during expansion. Syntax and nesting checks precede recursive processing/allocation of unbounded record children; byte parsing has its own bounded containers, depth, and integer tokens.

Measured across all 955 shapes/3 schedules:

- Largest encoded hint: 4,621 bytes (1x100 rows2).
- Largest charged expansion work: 26,158 (15x15 materialize).
- Largest finite expansion: 3,601 operations (15x15 inline).

These are bounded expansion measurements, not semantic-check accounting or performance claims. Decoder and syntax traversal have independent fixed byte/node bounds rather than being charged to semantic work.

## Frozen oracle and tests

Before implementing any new generator, the unchanged current planner produced 2,865 hashes in `axiom/tests/fixtures/bounded_loop_v1_stream_hashes.json`. Hash input is compact JSON of `[scratch_capacity_cells, [[opcode,dst,operands,index,value],...]]`. Origins, labels and source-offset metadata do not enter this executable stream hash. The fixture records baseline `39dc2f6df136c643cfd030ce4470503e807750fe`. The exhaustive test compares new expansion hashes to these frozen values, while separately requiring correspondence with the actual current finite Plan. It does not generate both sides with the new loop generator.

RED:

`PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_correspondence.BoundedLoopTests.test_raw_identity_and_metadata_do_not_grant_authority`

One expected assertion failure: independent bounded correspondence was not implemented.

GREEN:

`PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_correspondence`

6 tests passed in 51.818s, including 955 shapes x 3 schedules against frozen hashes.

`PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_codec`

11 initial adversarial tests passed in 0.030s.

`PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_codec tests.test_planner.PlannerTests.test_h5w7_checked_costs_and_canonical_bytes`

13 tests passed in 0.085s after adding explicit negative-component parity coverage; includes the existing representative finite checker/canonical-byte test.

`python -m compileall -q axiom/src/axiom/bounded_loop_model.py axiom/src/axiom/bounded_loop_codec.py axiom/src/axiom/bounded_loop_correspondence.py axiom/src/axiom/bounded_loop_planner.py`

Passed. Full production suite intentionally not run per task instructions.

Adversarial cases cover changed/negative/overflowing indices, overflow before parity and before cancellation, wrong parity, off-by-one staging bounds, wrong grouping, omitted/duplicated/dead/suffix operations, larger scratch capacity, invalid source/semantic/shape binding, aliasing/shadowing/scope escapes, bool-as-int, huge integer tokens, duplicate JSON keys, malformed Unicode/JSON, byte/syntax/depth/operation/work quotas, nested empty loops, zero-trip leaves under many-trip ancestors, exact work cutpoints, metadata-only edits, and raw whitespace identity.

## Self-review and limitations

The expander imports neither the generator nor source-expression semantics. Correspondence is complete structural enumeration, not functional proof. The generator intentionally uses no source formula substitution in the checker. All source/plan/semantic authority remains with the owning coordinator.

The finite planner and structured planner each consume the same untrusted schedule choice. Both remain untrusted; the frozen independent baseline prevents a new shared generator bug from self-certifying in tests. Production correspondence compares the actual supplied stream.

Signed intermediate indices and mathematical parity require careful backend lowering; the generator currently uses only nonnegative terms. Arbitrary valid finite plans or unmatched optional hints must keep existing emission with a diagnostic fallback reason; that integration is outside this task. Matching correspondence alone cannot prove an emitter correct.

Frozen records/private Python names are not protection against hostile Python code in the same process. Public byte/record APIs must continue fresh admission and cannot accept this result as authority.

Scalable v2 F1 remains BLOCKED. No >256 source admission, new semantic eligibility, code generator, backend, or scalable proof was added.
