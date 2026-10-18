# Residual validator independent review

Verdict: **PASS** for specification compliance and code quality. No important correctness, regression, or maintainability findings.

Reviewed commit `00daacfd684cf0d5dba588c9fd508ca7144d8f3d`, its immutable review package, the residual-validator brief, the implementation report, the production codec, and the frozen baseline/new differential tests. This review makes no production or test edits.

## Compatibility and trust boundaries

- The only changed production definition is `_validate_plan` (independently checked by comparing parsed definitions against baseline `21f36d4e977ff950276fbfff6198d8640bb24029`). Public validation/encode/decode signatures, the `None` public validation result, canonical serialization, and digest calculation are unchanged.
- Every former integer-helper call in the operation loop has the same exact-type predicate, inclusive bounds, error code, field path, and literal error message. `bool` and integer subclasses remain rejected. Record/opcode/tuple checks, dense SSA and prior-definition ordering, reserved scratch bounds, nullable fields, and literal/origin bounds retain their original order. Header/Unicode validation is unchanged.
- Canonical accounting retains the same header size, operation shell size, inter-operation comma, minimum origin precharge, and per-origin extra digit increments. Each comparison against `plan_bytes` occurs at the same point, including zero-increment charges and origin-element validation before that element's additional charge. Error precedence and partial-origin quota locations therefore remain equivalent.
- Actual multiplication count is accumulated from the inspected opcode stream, and workspace remains four times the validated reservation. Metrics return only after every operation and origin passes. No generator-provided counts, cache, trust shortcut, or alternate serialization was introduced.

## Evidence and test quality

Independently verified that the committed frozen codec is byte-for-byte equal to the historical source and has SHA-256 `5c8c67adb70760ffe7b4907701e8655a4af7b21d17cec26c5aba4247c46ebf49`. Its validator helpers are independently executed in a separate module, and its runtime loader does not require Git. The working codec also matches the reviewed pinned codec.

The new tests compare exact rejection tuples (code, field path, complete exception string), successful metrics, and canonical bytes against that oracle. They cover all seven opcode shapes, generated candidates, hostile scalar/container fields, nonprior SSA, reservation/literal limits, Unicode labels, operation limits, and every byte budget for empty/one/two-operation records plus malformed origins. This directly exercises both incremental origin checks and operation commas. Deterministic tracing/profiling assertions measure removal of eager diagnostic formatting and generic integer calls without flaky elapsed-time thresholds.

The report records 91 focused integration tests passing, 23 codec/hotpath tests passing under optimized Python, and five hotpath tests passing without Git on PATH. These are supplied execution evidence; this review did not rerun them or the broad selection sweep. The reported interrupted broad sweep is explicitly not treated as a successful run. The single profile's 32,608-to-6 integer-call reduction and unchanged metrics support the intended mechanism; its elapsed time is appropriately described as diagnostic rather than browser qualification.

The intentionally duplicated inline predicates/messages remain small and easy to compare with `_integer`; the frozen differential oracle protects their compatibility. Changes stay within lazy diagnostic allocation and guard/quota-call overhead reduction.

## Process artifact

The accidentally tracked ignored SDD implementation report is already assigned to the controller for untracking during evidence finalization. It is a process-artifact cleanup, not a runtime defect or a reason to block this codec change. Final full-suite and browser qualification remain the controller's responsibility under the brief.
