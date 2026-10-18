# Task 5 independent review

Reviewed immutable commit `a372dd8`, Task 5 brief/report/scoped diff, and the committed ownership, hint decoder, correspondence, planner and native driver dependencies. No implementation files changed. Runtime/latency qualification remains separate.

**Spec compliance: CHANGES REQUIRED. Code quality: CHANGES REQUIRED for one bounded edge case.**

## P2: zero-trip loops can produce uncompilable C

Location: `axiom/src/axiom/bounded_loop_c.py:59–62`.

The emitter recursively emits every loop body, including loops with equal start/stop. Such bodies contribute no finite operations, so fresh correspondence correctly does not require their scratch operations to have reachable addresses. For an eligible inline plan with `scratch_capacity_cells == 0`, append this node to its otherwise matching hint:

```python
Loop('never', 0, 0, (
    Primitive('scratch_load', 'unused', index=IndexExpr(0)),
))
```

The hint is accepted and compact emission succeeds, but generated C contains `scratch[ax_index_6]` without declaring `scratch`. Clang rejects the artifact before optimization. This breaks emission for an accepted, exactly corresponding hint; no forged receipt or modified checked plan is involved. A caller's typed-hint-error fallback cannot catch a compiler error after emission.

Confirmed against a temporary `git archive a372dd8` snapshot, using actual Clang 19 with `-std=c11 -O3 -Wall -Wextra -Werror`: exit 1, `error: use of undeclared identifier 'scratch'`. The reproducer used `stencil_source(1, 1, None)`, owned/authorized `inline-v1`, and the appended node above. No full test suite was rerun.

Recommended fix: omit zero-trip loops during C lowering, retaining raw hint identity and fresh correspondence. Their expanded stream is empty, so this preserves every actual finite operation. Add a focused regression compiling and executing a matching zero-trip hint with unreachable scratch access and zero scratch reservation; cover nesting as well.

## Other reviewed contracts

No additional correctness findings. Live identity-based owned authorization precedes fresh actual hint correspondence in the same call, and no caller-supplied correspondence is accepted. Lowering consumes lexical nodes in order, including reached dead operations, with separate safe identifier prefixes. Scalar arithmetic and ordered index offset/multiply/accumulation widen first; negative parity uses unsigned `& 1`. Decoder bounds loop counters and correspondence checks every reached index intermediate. Scratch reservation and stage/consume/refill order match the actual finite stream.

Shared preamble/driver helpers preserve the complete row-major preflight before writes, first-invalid status, initialized output/input preservation, exact dimension/token handling and documented disjoint ownership contract. Static comparison supports preservation of legacy finite C formatting; the report additionally records nine unchanged finite C digests. Compact output header uses beryl. Added metadata has compatible defaults and binds codegen version, raw hint bytes, correspondence version, source and plan identities.

The report's 17-test GREEN evidence covers real native execution, all schedules/boundary shapes, independent AST/finite observations, changing inputs, canaries, poisoned scratch, rejection state, malformed drivers, and three rehashed faulty emitters. Inspection confirms those tests compile and execute actual C and compare observations rather than trusting hashes. The reported 15×15 source reductions exceed 10×. Paired cold-build latency, compiler phase/IR/object/link measurements, throughput qualification and coordinator fallback integration are still pending and are not certified by this review.

## Scoped fix re-review: ADDRESSED

Reviewed immutable `a372dd8..f71e12d` backend/test diff against `task-5-fix-review-package.txt` and the appended RED/GREEN evidence. The P2 zero-trip finding is **ADDRESSED**. No new correctness or code-quality findings in the fix.

The new equality guard at `bounded_loop_c.py:63` skips only loops with zero iterations, after live ownership and fresh complete correspondence have succeeded. Nonempty loops and all reached primitives, including dead scalar operations, retain their existing lowering. No authority, index validation, preflight or reservation rule is weakened.

The regression tests both bound endpoints (0 and 256), zero scratch reservation, every arena operation kind, nested unreachable operations and unreachable invalid index arithmetic. It compiles actual emitted C, compares valid/rejected full observations against AST/finite interpreters, and asserts exact C equality to the original nonempty baseline. Raw hint identity remains distinct. A malformed name in an unreachable body still raises `HintError`, confirming that omission does not bypass lexical validation.

Reported evidence: before fix, both endpoint cases fail real Clang compilation with undeclared `scratch`; after fix, the focused test passes and all 18 covering native tests pass. These include the existing reached dead-operation test and boundary schedules. No unresolved issue justified repeating the suite, so this re-review used static committed-code inspection plus the supplied execution evidence.

The earlier backend correctness/code-quality objection is cleared. Separate runtime/latency qualification and final integration remain outside this scoped verdict.
