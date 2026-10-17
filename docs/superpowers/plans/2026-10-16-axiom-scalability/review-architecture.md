# Independent architecture and implementation-plan review

Date: 2026-10-16. This is a planning review, not implementation verification.

**Final review outcome: PASS for the inspected planning scope.** All three findings below are resolved in the revised documents and were independently rechecked. The native, proof and measurement implementation gates remain unpassed; this outcome establishes planning readiness within this review's scope, not evidence that the proposed properties already hold or authorization to expand the current planning-only task.

## Scope and method

Reviewed `README.md`, `design.md`, `01-core-buffer-and-native-build.md` and `02-compact-plans-and-checker.md`. Cross-checked the relevant current Axiom frontend/model, emitter and runner boundaries, and Core's List C representation/helpers, range-loop lowering, borrowed parameter signatures and immediate `defer` lowering. No product code was changed, no compiler/build was run, and no new correctness, native, performance or proof result was established. The native evidence/measurement and research-publication plans are outside this review's primary scope.

The proposed architecture is consistent with the inspected Core implementation: the production AST backend has the List representation needed for a private owned host, while its existence does not establish successful binding or scalable execution. The early native and proof feasibility gates are necessary. No blocking soundness contradiction was established in the written restricted proof approach; its actual rule kernel and hand-derived obligations remain unimplemented and require the planned independent review.

Line references below identify the draft reviewed; later edits may move them.

## Findings

### A1 — Medium: make machine-index lowering a separately tested admission obligation

**Locations:** Core plan lines 55, 262–269; loop plan lines 82–86 and 108–110; shared design line 76.

The design correctly requires all emitted i32 intermediate values to fit, but its named Core-emitter controls initially covered generic unsupported operations/profile mismatches rather than the boundary between mathematical affine normalization and machine evaluation. The proof IR permits bounded integers substantially wider than i32. An affine expression can normalize to an in-bounds address even when a naive sequence of emitted i32 multiplications/additions overflows; similarly, a mathematical empty loop can have bounds that the selected Core index type cannot represent. Shape bounds alone do not close either gap. Negative mathematical modulo and native remainder also need an explicit lowering decision.

**Minimal fix:** state that native emission either lowers an independently bounded normalized expression or returns a typed unsupported native-lowering result before compilation. Preserve the valid mathematical checker result rather than relabeling a backend limitation as semantic invalidity. Add named controls for canceling large affine intermediates, out-of-i32 physical-loop bounds, and a negative modulo operand. The cancellation control should distinguish safe normalization from unsafe literal lowering, not require rejection of a safely normalized equivalent. Require the native integration controls to exercise the actual emitted representation.

**Status:** resolved and rechecked. Core section 2.1 now requires an independent check of every actually emitted index/control intermediate, distinguishes mathematical validity from typed `NativeLoweringUnsupported`, and addresses terminal loop updates and modulo semantics. B4 names cancellation, negative-modulo and physical-loop-bound regressions, with a native-result check whenever safe equivalent emission succeeds. A final cross-plan check reconciled the physical-loop fixture with the updated nonnegative-i32 bound grammar: forbidden bounds reject at admission; an eligible empty loop at `INT32_MAX` tests emission/elision; valid affine/flattening cancellation exercises the separate lowering obligation. This closes the planning gap; implementation still has to satisfy those tests.

### A2 — Medium: freeze the complete deterministic ranking policy

**Location:** loop plan C9, initially line 227.

The phrase “primary requested abstract metric, secondary metric and stable candidate ID” leaves the secondary key and tie order unspecified. This is consequential when storage accounting is promoted: two independent implementations can use different rankings while both claiming the same policy version. Exact replay and frozen research policy need the full ordering, not just a version field.

**Minimal fix:** give one explicit ascending lexicographic tuple for each supported objective, define the stable final tie key, and specify how an unavailable optional metric is handled. Make `test_exact_ranking_and_stable_ties` assert those tuples. Do not let an optional diagnostic silently change arena-only or multiplication-first ranking.

**Status:** resolved and rechecked. C9 now supplies exact tuples, ASCII plan-ID ties, complete/nonnegative metric requirements and explicit examples. C8 separately freezes generation order as inline, materialize, rows2. The specified examples are consistent with the arena and multiplication equations; optional abstract storage does not alter the other two ranking tuples.

### A3 — Medium: assign the promised v2 CLI integration

**Locations:** initial loop plan C10 line 235; initial Core tasks B1–B8.

The initial C10 text assigned outer CLI integration to the Core workstream, but no Core task owned a CLI module, interface, invocation examples or tests. This left a promised integration surface unowned even though all subsystem APIs could be completed.

**Minimal fix:** add an explicit integration task with a separate v2 entry point and regression tests preserving v1 defaults, or declare the milestone API-only and remove the unowned handoff.

**Status:** resolved and rechecked. Master task I1 names its owner, dependencies, `scalable_cli.py`, tests, user guide, plan/check/replay/compile interfaces, explicit profile, exit meanings and native-build integration. C10 and the shared interface table agree with that ownership. V1 defaults remain unchanged and actual native correspondence remains the separately owned research command.

## Independently noticed dependency issue already being repaired

The initial native binding spike B2 required the operation allocator while B3 both implemented that allocator and depended on B2. The updated B2 now limits itself to a minimal binding/lifetime probe and explicitly defers complete allocation accounting; B3 step 7 installs the operation allocator and independent coverage control, repeated at integration. That change removes the implementation dependency cycle while preserving the stronger measurement gate. This issue was also found by the integration lead and is recorded here as resolved, not counted as an additional outstanding finding.

The integration lead additionally identified symbolic-expression expansion as a resource risk. Rechecked the added interned term-DAG requirements: at most 65,536 symbolic nodes and depth 256, enforced before excess allocation; shared references cannot become eagerly expanded trees during construction, hashing, substitution or comparison. C4/C5 now require bounded comparison, a 128-node shared-operand chain, node/depth quota rejection and a mismatched-source comparison control. These controls address a distinct risk from runtime-cell unrolling and preserve incomplete/unknown on resource exhaustion. They remain proposed tests, not measured memory or runtime results.

## Boundaries accepted by this review

- Missing/failed certificates remain semantic unknown; independently established counterexamples and malformed artifacts have distinct treatments. Fuel exhaustion does not produce exact incomplete metrics.
- Output effects cannot be forgotten with scratch facts. The rows2 invariant covers the initial row, parity-preserving refill, column prefix and loop exit without enumerating runtime cells.
- Index/control values cannot carry scalar payload. The arena property is deliberately weaker than combined abstract SSA storage, whose promotion has a separate gate and no native-memory implication.
- Source/specialization/candidate identities are fresh-checked; downstream compiler correctness remains empirical. Rehashed faulty-emitter controls must reach independent observation comparison rather than be treated as evidence that matching hashes imply correct lowering.
- The checked-call interval includes preflight, exact scratch setup and cleanup. Full state acquisition happens afterward and is still mandatory. Recoverable OOM, descriptor failure, process failure and incomplete acquisition cannot manufacture a successful semantic result.
- The native host uses actual generated types and original ownership records for cleanup. It makes no arbitrary-pointer or hostile same-process safety promise. The known Core baseline failures remain explicit.

The remaining principal research risk is whether the restricted proof language actually proves all required schedules, independent positive controls and exact metrics within the proposed quotas. C1/G2b makes that uncertainty an early stop decision rather than an assumed result. Exact compiler binding and complete allocator coverage are likewise still qualification questions, not completed properties.

## Final bounded amendment recheck

Rechecked the final `NativeQualification` ownership paragraph against the actual existing `core_toolchain.Toolchain` record. B5 owns the build-route extension, B2/B3 supply its binding/lifecycle controls, O4 retains its declared inventory, and the later M2 measurement `NativeCapability` is separate. The build route does not require future oracle/performance admission, so this clarification introduces no qualification dependency cycle. The shared design also forbids callers from widening registered source-profile maxima while retaining the profile identifier; operational limits may tighten the profile.

Rechecked the B7/O6 campaign alignment: O6 owns one frozen production manifest with 78 development calls, 24 larger ordinary calls and 16 deliberate fault calls, totaling 118. B7 reviews those exact receipts and runs its separate focused debug/optimized/sanitizer controls. The documents no longer imply two duplicate large campaigns. These bounded amendments introduce no new findings; the final planning-scope PASS remains unchanged. No proposed campaign was executed during this recheck.
