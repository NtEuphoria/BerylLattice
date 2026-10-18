# Residual correspondence optimization

Status: DONE. Independent review and root performance qualification remain integration gates.

## Implementation

Added `_validate_owned_loop_correspondence(owned, hint_bytes, hint_limits=HintLimits())`. It first calls `compilation._require_owned`, then freshly decodes the exact hint bytes. Shared `_expand_operations` retains the original lexical validation, exact source/semantic/shape binding, saturating traversal and operation-count prechecks, charged control/index/SSA steps, checked-i32 intermediate evaluation, and specialized arena bounds. Shared `_match_operations` compares exact reservation, count, opcode, dense destination, ordered operands, index, and value across the entire stream.

The private helper reuses the successful check's retained canonical finite `plan_digest`, retains the exact `owned.plan` object, hashes exact raw hint bytes, and returns the original source/semantic bindings. It does not invoke finite validation/encoding or construct an artificial expanded Plan. Its result has `expanded_plan=None`; this is explicitly documented. Expanded executable operations remain transient, bounded by the existing finite operation limit, and fully compared before acceptance. The helper neither grants eligibility nor accepts a caller-created correspondence as authority.

Public `validate_loop_correspondence` and `expand_loop_program` keep their original validation, canonical encoding, artificial expanded Plan output, and diagnostic behavior. Their computation shares the expansion and comparison implementations with the private path. No duplicated traversal implementation was added. No source, plan, hint, semantic, or scratch quota changed; the existing v1 boundary and scalable v2 BLOCKED status remain.

Compact C/Wasm changes are only imports and the helper call. Existing ownership checks and fresh correspondence per emission remain. One existing C test's spy target changed from the public correspondence function to the new private entry; its assertion still requires two independent correspondence calls for two emissions.

## Tests and evidence

RED:

`PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_owned_correspondence`

Seven expected failures asserted that the private owned helper did not yet exist.

Initial GREEN:

`PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_owned_correspondence tests.test_bounded_loop_codec`

19 tests passed in 0.098s.

Additional actual-backend callback control:

`PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_owned_correspondence.OwnedCorrespondenceTests.test_both_backends_use_owned_path_without_finite_rescans`

One test passed in 0.011s. After creating the owned successful check, two backend emissions produced exactly two fresh hint decodes, zero `_validate_plan` callbacks, and zero `_encode_validated_plan` callbacks. Trace counters reported two correspondences and no candidate-validation or encoding events for these emissions. Separate tests also count zero public finite validator/encoder calls on the owned path. Public validation and expansion still invoke their real finite validation/encoding callbacks.

Focused tests cover exact actual-plan object/canonical digest, raw source digest, semantic binding, raw hint bytes/digest including whitespace, unchanged work accounting, forged/closed/cross-context records, differing raw source with identical semantics, differing shape, malformed bytes, work exhaustion, hostile empty loops, metadata labels/origins, changed literals, missing/duplicate/dead/suffix operations, increased reservation, and complete checked-plan suffix rejection. Forged owned records are rejected before hint decoding.

Combined regression command:

`PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_correspondence tests.test_bounded_loop_owned_correspondence tests.test_bounded_loop_codec tests.test_bounded_loop_c tests.test_bounded_loop_wasm tests.test_compilation`

48 tests passed in 71.533s, with one skipped class because Clang was absent from PATH. This run includes the frozen 955-shape x 3-schedule corpus once, real V8 complete-memory observations, failure/preflight preservation, hint attack controls, and ownership regressions. The newly added backend no-rescan test ran separately as recorded above (it was added after this process started).

The skipped C suite is rerun with the repository's existing explicit LLVM toolchain:

`AXIOM_TEST_NATIVE_CLANG=/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_c`

9 tests passed in 3.635s with no skips, including real strict Clang compilation, source/finite observation comparisons, scratch poisoning and canaries, invalid-input preflight preservation, and deliberately rehashed faulty-emitter detection. No full production suite or performance sweep was started by this task.

## Self-review / limits

Removing artificial expanded-plan validation is safe only inside the live owned path: the entire executable stream is compared to its already structurally validated and successfully checked immutable actual Plan. Hint metadata is separately bounded and is neither emitted nor used as proof authority. Actual finite source/plan quotas were enforced by the owning transaction and are not replaced by hint quotas.

The private helper reuses the same in-process ownership contract as the backend; frozen records and private names are not a sandbox against hostile Python executing in-process. Public byte APIs still admit/check fresh, and no caller-supplied authority record can enter the backend path.

Expansion is still bounded enumeration and allocates a temporary operation tuple. This change removes redundant scans/serialization, not all correspondence work. No achieved latency or speedup claim is made; root qualification must measure that separately after integration review.
