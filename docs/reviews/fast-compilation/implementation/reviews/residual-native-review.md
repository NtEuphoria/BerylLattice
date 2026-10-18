# Residual native throughput change: independent scoped review

**Spec compliance: PASS. Code quality: PASS. No material findings.**

Reviewed immutable commit `b5f7d2ecfb4f89fe3ece34bfb4cca9d7d543f989` relative to `ae61f15`, the supplied `residual-native-review-package.txt`, and complete committed native helper/compact emitter context. Scope is the three changed backend/test files. This is a static review; no test, compilation or benchmark was run during the coordinator's active qualification work.

## Contract and semantics

- The existing public native docstring and generated kernel comment already require exact-sized, initialized, exclusively owned, disjoint arrays for the entire synchronous call, with no concurrent access or lifetime change. Adding `restrict` to the two compact parameters expresses that existing contract. The input is read-only, output accesses use its own pointer, and local scratch cannot alias either caller array. This does not extend caller obligations.
- The reduction reads only input indices `0..input_count-1`. All those cells are required to be initialized and stable even when an earlier cell is invalid, so reading beyond the first invalid cell is safe under the existing contract. No volatile or concurrently changing input behavior is promised.
- Each interval comparison produces 0 or 1, then an unsigned OR accumulates whether any cell is invalid. Comparisons remain valid for all i32 values, including both extrema; there is no arithmetic on input values or overflow-prone subtraction. If any cell is invalid, the second ordered scan uses the identical predicate and returns exactly the first invalid row-major index plus one. Input stability ensures the scan finds the invalid cell observed by the reduction. The existing 256-cell bound keeps loop counters and return values in range.
- Both passes precede scratch initialization and every emitted finite primitive/output store. Rejection leaves every input and initialized output cell untouched. Success reaches the existing body unchanged: primitive order/grouping, int64-first arithmetic, scratch reservation/lifetime, and zero-trip handling are unaffected. The `ax_invalid` local is disjoint from the emitter's scalar, index and loop identifier prefixes.

## Scope and compatibility

Only the compact emitter enables the two new helper options. Their defaults are false, so finite emission interpolates the empty qualifier and uses the identical original preflight string. All other finite formatting and helper logic are unchanged; therefore finite C bytes are preserved for every supported plan, not just the fixed regression examples. The new tests additionally pin public finite digests across all three schedules and compare private/public finite output before and after compact emission.

Header branding, include/driver content, storage limit, artifact field layout and metadata generation are unchanged. Changed compact bytes continue to receive their exact generated-C digest. There are no admitted-profile, quota, checker, hint, operation-metric, Wasm, public export manifest or compiler-flag changes in this scoped commit.

## Validation evidence and limits

The supplied report records 22 targeted real-Clang tests passing. Inspection confirms the added tests check frontend LLVM `noalias` contracts at O0 (both compact parameters and unchanged finite parameters), a vector predicate/reduction inside the optimized kernel, and full native input/output/status observations for every invalid position, both i32 extrema, multiple invalid values and valid reuse after rejection across all schedules. Existing boundary, canary, scratch poison, grouping and malformed-driver tests remain in that covering command. These are meaningful checks of the intended mechanism and behavior.

The earlier full-suite result (445 executed with 22 Core prerequisite skips) precedes this delta and is not a post-delta full-suite claim. The supplied seven-pair probes for all four cases support proceeding to final qualification, but this review does not certify timing or the 10% throughput gate. The earlier 21-sample misses (5×7 ratio 1.2294 and rows ratio 1.1013) remain historical evidence; final 21-sample qualification is coordinator-owned and pending.
