# Task 4 independent review

Reviewed revision: `a379571`, using the immutable scoped review package and `git show a379571:<path>`. Scope: bounded model, codec, planner, correspondence, adversarial tests, and frozen corpus contract. Other working-tree changes were not reviewed or modified.

## Verdict

**Spec compliance: PASS for this task's bounded representation and correspondence scope. Code quality: PASS.** No load-bearing correctness or quota finding requiring a change was identified. Backend integration and successful complete finite checking remain separate coordinator gates; this review does not establish either gate or scalable v2 eligibility.

## Evidence

- The model explicitly separates `beryl-bounded-loop-v1` from scalable v2. Exact integer checks preserve positive admitted dimensions and the 256-input boundary. `HintLimits` cannot raise the fixed byte, syntax, depth, or work ceilings (`bounded_loop_model.py:23-35`; `bounded_loop_codec.py:33-45`).
- The decoder uses the existing bounded strict JSON parser, requires complete field sets, and checks loop depth and syntax before recursive record construction. Record validation checks immutable container types, primitive arities, lexical definitions and uses, bounded indices and origins, and exact integer/boolean types (`bounded_loop_codec.py:61-123`, `135-191`). Byte parsing independently rejects duplicate keys, malformed Unicode, floats, oversized integer tokens, and excessive containers/depth.
- The precheck saturates operation and work counts, charges every loop control and each iteration's binding/removal, and counts primitive, operand, definition/cleanup, and ordered index work. Empty bodies and zero-trip descendants therefore cannot hide exponential traversal. The expander independently charges these steps and checks measured totals against predictions (`bounded_loop_correspondence.py:71-105`, `109-149`).
- Scalar bindings are fresh dense finite SSA identities on every executed iteration. Definitions are removed at lexical block exit; prior lexical validation forbids shadowing, forward uses, and escaped definitions (`bounded_loop_codec.py:69-95`; `bounded_loop_correspondence.py:109-146`).
- Index evaluation checks the initial constant, variable-plus-offset, optional mathematical modulo two, multiplication, and accumulator addition in the declared order. The final index is checked against the specialized arena. Negative intermediates are allowed only when signed-i32 valid; parity remains nonnegative (`bounded_loop_correspondence.py:41-68`, `129-135`).
- Correspondence imports neither the generator nor source-expression semantics. It validates the actual finite Plan, requires matching source/shape specialization and reservation, compares operation count and every executable field in order, and retains the supplied Plan, canonical finite identity, and exact raw hint bytes/digest. Valid label/origin changes are excluded from executable equality but remain structurally validated (`bounded_loop_correspondence.py:161-179`). The result grants no eligibility.
- The untrusted generator preserves the hoisted constant and v1 two-row stage/consume/refill sequence (`bounded_loop_planner.py:53-66`). Its exhaustive test compares expansion against 2,865 frozen hashes attributed to the pre-change planner, independently of the new generator, and separately compares the supplied finite stream (`test_bounded_loop_correspondence.py:35-49`).

## Validation reviewed and limits

Relied on the implementer's recorded passing exhaustive 955-shape × three-schedule correspondence run and recorded passing hostile-codec tests; did not rerun that corpus, per review instructions. Inspected the targeted tests for intermediate overflow before parity/cancellation, lexical escapes, parity/bounds/grouping mutations, dead/suffix operations, metadata changes, exact work cutpoints, nested empty traversal, and hostile bytes/records.

No production code or tests were edited. The only review artifact written is this report. Optional-hint fallback diagnostics, retention of the separate complete finite check, emitter correctness, public fresh-admission boundaries, and external raw finite-plan byte identity belong to integration; their completion is not inferred from this internal correspondence result. The existing >256 and scalable-v2 F1 restrictions remain unchanged.
