# Independent source oracle and complete native evidence implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. This document specifies future implementation; it records no new native execution or performance result.

**Goal:** Produce complete expected states directly from original Axiom source, then independently compare every observed native invocation at the supported large shapes while retaining bounded, replayable evidence.

**Architecture:** A low-level immutable invocation transport is shared by production and research code. A source-AST evaluator, independent of plans and lowering, produces expected state; a separate acquisition verifier observes native bytes and performs complete comparisons before content sharing. Native v2 coordinates separate semantic and toolchain qualification stores while preserving every v1 contract.

**Tech Stack:** Python 3.12+ standard library; canonical bounded JSON; SHA-256 identities; signed little-endian i32 chunks; existing descriptor-relative immutable artifact operations; the reviewed Linux native host from plan 01.

**Spec:** [Shared design](design.md); [Core buffer/native plan](01-core-buffer-and-native-build.md); [compact-plan/checker plan](02-compact-plans-and-checker.md); [native experiment plan](04-native-measurement-and-experiments.md).

## Global Constraints

- Core is the separate 4GL; Axiom is the experimental 5GL. These plans do not publish either confidential project.
- Existing source/plan/state/receipt/export v1 behavior remains unchanged, including native admission being unavailable in v1.
- The large profile admits positive output H and W, each at most 8192, with P=(H+1)*(W+1) at most 8,388,608. O=H*W. All extent arithmetic is checked before consuming streams or allocating buffers.
- Arithmetic is exact signed i32 at every original scalar node; source input values must be in [0,1023]. Whole-input row-major preflight precedes all producer/output work.
- Input is immutable, output is exclusive and disjoint, and every initial-output scalar is preserved on input-precondition failure.
- Source bytes, family semantics, specialized semantics, invocation, physical plan, emitted kernel, executable and individual run have separate identities.
- The shared invocation transport contains no oracle, plan generation, semantic optimization, or measurement computation.
- Canonical evidence uses signed little-endian i32. The host ABI must independently qualify its representation and conversion obligations.
- A completed semantic state has only success or input_precondition_failed. OOM, cancellation, timeout, malformed boundaries, capture failure and oracle exhaustion are distinct non-completed execution/evidence outcomes.
- Semantic store: at most 268,435,456 unique retained bytes, 16,777,216 bytes per file, 1,048,576-byte chunks, 16,384 files. Metadata is at most 1,048,576 bytes per document, depth 16 and 65,536 items. Qualification store: separately at most 536,870,912 unique retained bytes with the same file/chunk/count/metadata bounds. Neither changes v1.
- The semantic bound is per admitted stratum capsule. A campaign binds at most 256 stratum roots and 131,072 files overall, one shared qualification root, at most 8 GiB retained semantic bytes and a separate 1 GiB failure quarantine. Unique-path accounting traverses the complete campaign index, so splitting references across roots cannot evade these bounds.
- Temporary capture disk is at most 256 MiB for the single active acquisition. Reserve space before launch. Filling temporary storage or failure quarantine stops incomplete and preserves existing outcomes; it never authorizes discarding unfavorable samples.
- Every native invocation acquires and compares all required bytes before semantic state may be shared. Identity hashes alone never establish comparison.
- No new test computes or executes fresh held-out data. Use the disclosed training and correctness cases; retain historical primary/thin-shape exposures in plan 04's ledger.
- New code is verified with normal and optimized Python. Product checks use explicit errors, not assertions that disappear under -O.

## Review Focus

- A canonical state reused by hundreds of invocations must not conceal an invocation that never ran or never captured its last bytes; O5 tests acquisition absence and skipped-final-chunk controls.
- A valid typed invocation object whose underlying files are replaced must fail at the oracle/native boundary; O1 and O3 tests mutate verified files after construction.
- Equal logical states do not imply equal exact source identities, and specialization identity cannot substitute for family identity; O1/O3 test renamed sources, changed H/W and forged bindings.
- Source and native failure paths must preserve nonzero initial output and distinguish invalid input from allocation or evidence failure; O2/O6 test multiple invalid cells and injected OOM/capture faults.
- Read amplification from comparison, deduplication and replay must not evade a logical-work budget merely because only one state is stored; O5 tests separate storage, acquisition and logical-read counters.

## Ownership and dependencies

Plan 02 owns source_profiles.py and its admit_source_v2 result, AdmittedLoopKernel. This plan consumes that profile but does not alter the plan checker or its proof rules. Plan 01 owns loop_core_emit.py, core_native_v2.py, and axiom/native/v2/{buffer_host,host_protocol,operation_allocator}.{c,h}; this plan does not create a second host or allocator under research.

The following new files have one owner:

| File | Responsibility |
| --- | --- |
| axiom/src/axiom/artifact_chunks_v2.py | Bounded typed arbitrary-byte blob transport; production-safe dependency. |
| axiom/src/axiom/invocation_v2.py | Exact source/buffer invocation identity and immutable verified transport. |
| axiom/research/source_oracle.py | Interpretation of original source equations over bounded readers. |
| axiom/research/oracle_receipt.py | Bind expected state to actual source invocation and qualified oracle identity. |
| axiom/research/evidence_stores.py | Two-store closure traversal and complete qualification inventory. |
| axiom/research/native_acquisition.py | Validate one native capture and perform independent complete comparison. |
| axiom/research/state_store.py | Share canonical state only after per-invocation comparison; account work. |
| axiom/research/tests/test_large_correspondence.py | Cross-plan source/native integration and fault controls. |

Use existing state_artifacts.py as a versioned dependency; do not refactor it gratuitously. If a new generic blob format needs similar descriptor-relative primitives, put the v2 implementation in the low-level module and retain v1 compatibility tests. Avoid a production import of research modules.

All task commands below run from /workspace/BerylLattice/axiom unless stated otherwise. Prefix Python commands with PYTHONPATH=src:research. Native tests must fail preflight when explicitly requested without qualification; ordinary portable unit discovery may mark a clearly named native-only test unavailable. A skipped native test never satisfies a task's native exit gate.

## O1: Shared bounded blob and invocation transport

**Dependencies:** Plan 02's source-profile contract; plan 01's host transport schema review. Can be implemented before native execution exists.

**Files:** Create src/axiom/artifact_chunks_v2.py, src/axiom/invocation_v2.py, tests/test_artifact_chunks_v2.py, tests/test_invocation_v2.py, and research/protocol/invocation-v2.md.

**Interfaces:**

- BlobReference names an immutable manifest of exact byte length and ordered contiguous chunks, each with length/path/hash. A blob is not a semantic state.
- BlobLimits fixes chunk/file/metadata/count bounds; enclosing stores own aggregate budgets.
- write_blob(blocks: Iterable[bytes], byte_length: int, directory: Path, *, limits: BlobLimits) -> BlobReference.
- verify_blob(reference: BlobReference, *, limits: BlobLimits) -> VerifiedBlob.
- VerifiedBlob.revalidate() and iter_bytes() recheck actual identities; bounded read_i32(index: int) uses checked offsets and little-endian decoding.
- InvocationManifest binds source bytes/hash, family_semantics_sha256, specialization_semantics_sha256, source_profile, H, W, input and initial_output blob references, and explicit disjoint owned-buffer boundary.
- verify_invocation(manifest: Path, *, limits: InvocationLimits) -> VerifiedInvocation.
- VerifiedInvocation exposes source_bytes, source_sha256, family_semantics_sha256, specialization_semantics_sha256, H, W, input, initial_output, invocation_sha256, and revalidate(). Input/output lengths are exactly 4P and 4O.
- Invocation identity hashes canonical source/shape/contract/input/initial-output identities; it excludes physical plan, run, path and timing. Do not confuse it with state-v1's semantic invocation identity: retain an explicit mapping between the two domains.

- [ ] Write test_chunk_transport_exact_coverage, test_chunk_reader_bounds_and_endianness, test_invocation_exact_source_and_family_bindings, test_invocation_extent_rejected_before_iterator_read, and test_verified_invocation_revalidates_mutated_files.

  Assert duplicate keys, booleans as counts, negative/overflowed offsets, missing/overlapping chunks, symlinks and partial final scalars reject. For W=2047/H=2049 assert P=4,198,400 and exact input/output lengths 16,793,600 / 16,777,212. This assertion is arithmetic-only; do not generate the historical primary input in this task. For W=2048/H=2048 assert 33,570,820 combined state bytes. For a forbidden extent, use an iterator that raises if touched and assert zero reads.

- [ ] Run the new tests and retain the intentional RED result:

      PYTHONPATH=src:research python -m unittest tests.test_artifact_chunks_v2 tests.test_invocation_v2 -v

  Expected RED: missing v2 transport/API or a concrete failed boundary assertion, not an unrelated import/environment failure.

- [ ] Implement only the declared format/readers and immutable records. Enforce maximum H/W/P before aggregate arithmetic is converted to a native-size representation. Source/profile checks reparse source bytes through source_profiles.admit_source_v2; compare the resulting three identities, never trust caller hashes. A maximum of two 1 MiB input chunks may reside in the reader cache.

- [ ] Run the command above normally and with python -O; run existing tests.test_frontend and research/tests/test_state.py. Expected GREEN: all portable cases pass, v1 fixtures unchanged, mutation-after-verification rejects.

- [ ] Request independent schema/spec and implementation-quality review, resolve all important findings, then commit only owned files with message: feat(axiom): add bounded v2 invocation transport.

**Stop:** Do not let a dependency ambiguity create two incompatible invocation schemas. Reconcile field names with plan 01 before committing.

## O2: Source-AST streaming oracle

**Dependencies:** O1; plan 02's admitted large source profile. Native execution is unnecessary.

**Files:** Create research/source_oracle.py, research/tests/test_source_oracle.py, research/protocol/source-oracle-v1.md.

**Interfaces:**

- OracleLimits includes max_source_bytes=65,536, max_cached_input_bytes=2,097,152, max_scalar_evaluations=1,000,000,000, explicit metadata/state quotas, and cancellation/deadline configuration. The work cap is a declared operational bound, not a proof that every grouped source fits.
- evaluate_source_state(source_bytes: bytes, invocation: VerifiedInvocation, destination: Path, *, profile: SourceProfileV2, limits: OracleLimits) -> OracleResult.
- OracleResult is immutable. A completed result retains state_manifest, status, first_bad_index, source/invocation identities, and scalar_evaluations. Non-completed outcomes identify unsupported_source, invalid_invocation, work_limit, cancelled, allocation_failure or io_failure and cannot supply a completed expected-state receipt.

- [ ] Write test_streaming_oracle_matches_bounded_original_ast, test_preflight_visits_every_input_before_equations, test_preflight_multiple_invalid_preserves_nonzero_output, test_oracle_uses_source_nodes_not_stencil_shortcut, test_oracle_does_not_import_plan_modules, and test_oracle_budget_failure_is_not_semantic_failure.

  Compare every output/input scalar and status against reference.evaluate_source over the existing bounded correctness corpus. Pin the hand-worked [0,1,2,3] input to output [30]. All-1023 valid input yields producer 1,048,576 and output 4,194,304. Multiple invalid values report the earliest row-major offset and preserve every initial-output canary. Monkeypatch the equation evaluator to fail if called before a failed preflight; it must remain uncalled. A changed equation outside the admitted family returns unsupported_source and no expected result; the test does not extend this oracle to arbitrary source programs.

- [ ] Run:

      PYTHONPATH=src:research python -m unittest discover -s research/tests -p test_source_oracle.py -v

  Expected RED: the new evaluator is absent or fails a specific semantic independence/control assertion.

- [ ] Implement a visitor over original source AST nodes using Python integer arithmetic and a checked i32 result at every node. Bind producer reads to their declaration and requested logical coordinate, then evaluate that declaration; do not interpret physical-plan instructions, use optimizer canonical DAGs, or share ring-buffer lifetime code. Grouping and evaluation association remain intact.

  Revalidate invocation before consumption. Perform one full row-major input-range scan before equation work. On failure, stream original input and complete original output into state v1. On success, compute output in declared order using bounded logical reads and stream results. Every node evaluation increments an explicit work counter; cancellation and quota failure prevent completion publication. A source AST with excessive grouping may be unavailable rather than bypassing this bound.

- [ ] Add test_training_32_by_32_streamed_complete_state and test_chunk_boundary_coordinate_reads using disclosed training shapes. Assert the number of emitted semantic-state scalars is exactly P+O, cache allocation remains bounded, no complete Python tuple/dict of producer/output cells is built, and first/last cells cross chunk boundaries correctly. This emitted count is not the number of source input reads or AST evaluations: producer recomputation and preflight perform additional work, counted separately.

- [ ] Run both test sets normally and under -O, then existing tests.test_reference. Expected GREEN: complete-state equality, exact failure preservation, no planner/checker/emitter imports, no successful artifact on quota/cancellation failure.

- [ ] Obtain fresh independent semantic and quality review, including source-dependency inspection; commit: feat(research): evaluate large source states independently.

**Stop:** A fast hard-coded four-neighbor implementation is not a substitute for this source oracle. If performance of the oracle is inadequate, retain the correct implementation and separately review a source-only execution optimization before using it as a trust anchor.

## O3: Qualified oracle receipts and independent expected-state binding

**Dependencies:** O2. Review of oracle qualification identity belongs here; physical native measurement qualification belongs to M2, with admission in M6.

**Files:** Create research/oracle_receipt.py, research/tests/test_oracle_receipts.py; extend research/protocol/source-oracle-v1.md.

**Interfaces:**

- OracleQualification binds implementation files, Python executable and declared dependencies, source/profile/AST versions, reviewed test evidence, review record and trusted-base statement.
- produce_oracle_receipt(result: OracleResult, qualification: OracleQualification, destination: Path) -> OracleReceipt.
- verify_oracle_receipt(receipt: Path, source_bytes: bytes, invocation: VerifiedInvocation, qualification: OracleQualification, *, limits: OracleLimits) -> VerifiedOracle.
- VerifiedOracle contains a fully verified expected state, exact independent source/invocation pins and immutable closure. Its construction is not a permanent capability: consumers revalidate it.

- [ ] Write test_oracle_receipt_binds_exact_source_and_specialization, test_renamed_source_equal_state_distinct_source_binding, test_changed_expected_bytes_cannot_redefine_anchor, test_forged_qualification_does_not_admit, and test_incomplete_oracle_has_no_expected_receipt.

  Renamed/grouped sources may yield equal canonical semantic state but each receipt must identify its actual exact source. Changed H/W must change specialization and invocation, not the family identity. Replacing expected bytes and updating their self-reported digest must fail against the independently selected source/oracle anchor. A typed dataclass with invented success or review fields must not pass revalidation.

- [ ] Run:

      PYTHONPATH=src:research python -m unittest discover -s research/tests -p test_oracle_receipts.py -v

  Expected RED: missing receipt producer/verifier or accepted forged binding.

- [ ] Implement exact identity/closure traversal and explicit qualification selection. Retain shared parser/model/state-format dependencies in the trusted base. No receipt-supplied command executes; independently selected qualified oracle code produces expected state before any comparison. Proof/checker acceptance never substitutes for oracle execution.

- [ ] Run the tests normally and under -O, plus the existing synthetic receipt tests. Expected GREEN: v1 synthetic behavior remains unchanged, oracle substitutions reject, completed source execution produces a revalidatable expected-state anchor.

- [ ] Obtain independent review of the trust boundary and forged-artifact controls; commit: feat(research): bind source oracle execution evidence.

**Stop:** A file digest establishes identity, not oracle correctness. Missing review/qualification or missing expected bytes leaves independent native correctness unavailable.

## O4: Coordinated semantic and qualification stores

**Dependencies:** O1/O3 and plan 01's actual native build/qualification inventory. Can develop strict storage controls with small synthetic files before native inventory exists.

**Files:** Create research/evidence_stores.py, research/tests/test_evidence_stores.py, research/protocol/native-evidence-stores-v2.md.

**Interfaces:**

- EvidenceStoreLimits has separately named semantic and qualification budgets, never a shared unbounded override.
- inventory_qualification(qualification: NativeQualification, directory: Path, *, limits: EvidenceStoreLimits) -> QualificationStore.
- verify_evidence_stores(semantic_root: Path, qualification_root: Path, *, limits: EvidenceStoreLimits) -> VerifiedEvidenceStores.
- Each root manifest declares its schema, exact direct references, approved indirect-reference schemas, unique retained bytes and expanded logical bytes. The semantic root binds the qualification root hash. Actual traversal recomputes every count/hash.

- [ ] Write test_two_stores_enforce_independent_budgets, test_large_library_chunks_are_fully_traversed, test_qualification_unknown_reference_schema_rejects, test_missing_used_linker_or_runtime_fails, and test_duplicate_paths_and_equal_distinct_files_account_exactly.

  Simulate a library larger than 16 MiB using actual bounded chunks; corrupt a final byte and require rejection. A small root JSON with an unchecked oversized external path is invalid. Duplicate references to one canonical stored path count once, while equal bytes stored at different paths count twice. Missing inventoried components and changed lexical lookup targets fail.

- [ ] Run:

      PYTHONPATH=src:research python -m unittest discover -s research/tests -p test_evidence_stores.py -v

  Expected RED: absent store verifier or missing closure/limit enforcement.

- [ ] Implement typed blob manifests using O1's transport and fixed v2 store limits. Inventory actual Core/Clang/compiler configuration, driver/linker, used startup objects/SDK inputs, loader/runtime components, collector and oracle implementation dependencies. Preserve actual argv and lookup-path resolution evidence.

  The currently retained 17 Clang components total 237,929,136 bytes; LLVM, clang-cpp and Z3 individually exceed 16 MiB. This evidence motivates the separate store, but is not a claim that the complete future inventory already fits 512 MiB. Preflight the actual inventory and fail unavailable if it does not fit. Do not omit files to pass.

- [ ] Verify a real qualified native build inventory without timing a workload. Revalidate both original and retained bytes. Record which OS/hardware or dependency properties remain externally trusted; do not claim hermetic execution.

- [ ] Run normal/-O tests and existing state/export closure regressions. Expected GREEN: both stores fully checked; v1 limits remain exact; qualification overflow, stale runtime or undeclared dependency prevents native admission.

- [ ] Obtain fresh closure/provenance review and commit: feat(research): retain coordinated native evidence stores.

## O5: Per-invocation acquisition, full comparison and bounded state sharing

**Dependencies:** O3/O4; plan 01's NativeRunV2 completion and raw capture contract.

**Files:** Create research/native_acquisition.py, research/state_store.py, research/tests/test_native_acquisition.py, research/tests/test_state_store.py, research/protocol/native-acquisition-v2.md.

**Interfaces:**

- acquire_and_compare(run: NativeRunV2, invocation: VerifiedInvocation, oracle: VerifiedOracle, store: SemanticStateStore, *, limits: AcquisitionLimits) -> ComparisonReceipt.
- SemanticStateStore.intern_compared_state(capture: VerifiedCapture, comparison: VerifiedComparison) -> SharedStateReference is internal to the verified acquisition path; an arbitrary boolean or caller-created record cannot authorize sharing.
- ComparisonReceipt binds run/capture/invocation/source/plan/kernel/binary/collector identities, oracle identity, actual status, first failure, all completed byte counts, comparison result, canonical shared state and unique acquisition receipt.
- AcquisitionLimits and CampaignWorkBudget separately bound capture bytes, scalar comparison bytes read, CAS equality bytes read, verification/replay bytes read and persisted unique bytes.
- NativeRunV2 public fields are run_manifest:Path, run_sha256:str, invocation_sha256:str, completion:NativeCompletion, observed_capture:Path|None, timing_raw:Path|None and allocation_raw:Path|None. NativeCompletion is complete|boundary_error|resource_error|unavailable|timeout|cancelled|process_error|acquisition_error|integrity_error. Only complete has an accepted full capture; even that status requires independent oracle comparison.

- [ ] Write test_last_chunk_mutation_rejected, test_missing_native_acquisition_cannot_reuse_expected, test_same_wrong_results_rejected_by_source_oracle, test_input_mutation_rejected_even_when_outputs_match, test_per_run_receipts_survive_shared_state, test_hash_match_does_not_skip_byte_comparison, and test_cas_sharing_does_not_discount_acquisition_work.

  Use a reader that records the exact byte intervals consumed. Successful comparison must traverse all input/output bytes on both observed and expected sides. A forced hash-collision fixture must still fail actual equality. Two successful invocations with equal results may share one canonical state but require two distinct capture/comparison receipts and twice the acquisition-work count.

- [ ] Run:

      PYTHONPATH=src:research python -m unittest discover -s research/tests -p test_native_acquisition.py -v
      PYTHONPATH=src:research python -m unittest discover -s research/tests -p test_state_store.py -v

  Expected RED: missing acquisition path or a control demonstrating skipped actual observation/comparison.

- [ ] Implement capture validation from plan 01's owned host interface only. Revalidate NativeRunV2's retained raw manifest; do not trust its in-memory success field. Decode actual post-call input/output bytes and host status, compare complete state/status/first-invalid against the independent oracle, and independently compare post-call input with retained original input.

  A completed native failure receipt for OOM, timeout, crash, invalid boundary or incomplete cleanup cannot become state-v1 success or input_precondition_failed. It retains diagnostics but produces no admissible timing receipt.

- [ ] Implement the fixed byte-work accounting below and store it in the protocol and receipts:

  For one invocation let S=4(P+O). A successful captured state writes S logical bytes. The mandatory comparison reads S observed bytes and S expected bytes: 2S logical comparison reads. Independent input preservation reads 4P observed bytes and 4P original bytes unless fused into a documented single traversal with separate comparison counters; either implementation records actual reads, and the preregistered reservation uses the larger 8P bound. If CAS sharing performs another equality pass, reserve and charge 2S CAS comparison reads. State verification/revalidation and replay charge their actual read bytes in an additional counter.

  For N executions the required lower-bound reservations are capture_write=N*S, semantic_compare_read=2*N*S, input_preservation_read=8*N*P, and possible CAS_compare_read=2*N*S. Never substitute unique stored S for N*S. Reserve these components before launching a collection stage; add a separately declared verification/replay allowance.

  In the general per-stratum case N=2*n_pilot*b_pilot+2*n_final*b_final, plus separately counted training, qualification and failed attempts that consume acquisition work. A future final count may differ from the baseline pilot count. Only when both counts equal n and both batch sizes equal b is N=4nb; n=32,b=1 gives 128, while pilot32/final64 gives 192. Sum reservations per stratum with that stratum's P/S, rather than multiplying one shape by a whole mixed-shape campaign. Any batch requires capture/comparison of every actual call unless a separately reviewed batched-acquisition protocol exists.

  Freeze the pilot reservation before pilot execution. If baseline-only calibration selects a larger final count, append a final-stage reservation amendment and recheck the cumulative campaign quota before any candidate measurement. Preserve prior pilot work in the counters. Reservation failure leaves the campaign incomplete; it does not erase pilot evidence or authorize a smaller favorable prefix.

  Use exact integer counters and stop before exceeding a reservation. A work limit is not a performance observation. Default campaign logical I/O allowance is 1 TiB (1,099,511,627,776 bytes) summed over all actual logical read/write categories, with stored bytes still subject to their independent closure quota. A count/shape/sample declaration must calculate its bound; do not assume every 1024-pair batched campaign fits.

  The verification/replay reservation must list the actual number of full semantic and qualification closure walks performed by the declared code paths, multiplied by each actual inventoried closure size, plus bounded metadata reads. Include toolchain/qualification revalidation inside execution, admission and export. A single walk of the currently known Clang components is already 237,929,136 bytes; two such walks for 2304 training invocations cost 1,096,377,458,688 bytes before state capture/comparison or any further dependencies. Thus the 1 TiB default may reject the complete default training schedule. Stop before collection if the complete estimate exceeds it; a separately reviewed budget amendment must precede execution and retain the original campaign identity/history. Splitting the same experiment across nominal campaigns or silently omitting validation cannot evade the quota.

- [ ] Revalidate newly captured bytes against a candidate CAS object before deduplication. Retain every run-specific receipt and capture completion identity. The same observation/acquisition/comparison receipt cannot be reused across independent pairs even when their canonical state bytes are identical. Publish semantic manifests last, after all comparison and closure checks. Preserve mismatch artifacts within quotas for diagnosis; never publish an eligible partial state.

  Reserve the complete temporary capture before launch; cap one active acquisition's temporary files at 256 MiB. Failed-run artifacts enter the separately bounded 1 GiB quarantine, retain their original attempt identity and are included in campaign accounting. If quarantine or temporary space is unavailable, stop incomplete before another invocation instead of deleting prior evidence. Test full-quarantine, disk-full mid-capture and split-root quota bypass explicitly.

- [ ] Run normal/-O tests. Add a primary-size synthetic format/counter test using the already disclosed non-workload pattern, clearly labeled format-only; assert S=33,570,812, N=128 and all formula totals exactly. Expected GREEN: full traversal, exact separate counters, no hash-only or expected-copy shortcut, bounded temporary storage.

- [ ] Obtain independent acquisition/CAS/accounting review; commit: feat(research): verify every native state before sharing evidence.

## O6: Large correspondence and falsification gate

**Dependencies:** O1–O5; plan 01's qualified build/invoke APIs; plan 02's all-three-plan checks/emission. This is the correctness milestone and does not depend on a working performance collector.

**Files:** Create research/tests/test_large_correspondence.py, research/tests/fixtures/large-case-schema.json, research/large_correspondence.py; extend research/protocol/native-acquisition-v2.md.

**Interfaces:** run_large_correspondence(campaign: Path, qualification: NativeQualification, destination: Path, *, limits: CorrespondenceLimits) -> CorrespondenceResult. A frozen manifest lists exact source, plan, input, initial output, expected cases and required completion keys. The command does not silently skip unavailable cases.

This is the same G3 campaign consumed by B7's native integration review. Share its frozen manifest and exact receipts; do not run two identical large matrices for the two plan documents. Focused B7 debug/optimized/sanitizer controls remain distinct. A second reviewer revalidates retained evidence; repeat execution only when a relevant change, failure or unresolved concern requires it.

- [ ] Write test_training_shape_complete_source_native_correspondence, test_faulty_lowering_agreement_does_not_pass_oracle, test_oom_and_capture_faults_never_admit_state, and test_manifest_complete_keyset_required.

  Use one qualified production native configuration for this gate; debug/release host qualification is owned by plan 01. Partition the default matrix rather than applying every adversarial pattern to every maximum shape:

  - Development W32/H32 and W128/H128: nine valid patterns (zero, all-1023, coordinate ramp, four separate corner impulses, one interior impulse, and approved LCG seed1) plus four invalid patterns (first, middle, last, multiple), all three plans: 2*13*3=78 calls.
  - Larger W512/H512, W2048/H2048, W4096/H64, W64/H4096: approved LCG seed1 plus one last-invalid variant, all three plans: 4*2*3=24 calls. Initial output uses nonzero canaries.
  - On development W32/H32, wrong neighbor, missing final output store, altered first-invalid offset, changed input and truncated final capture each exercise all three plans: 15 fault calls. Premature live-row overwrite applies once to rows2: one additional fault call.

  Thus freeze exactly 102 ordinary cases and 16 deliberate faults before execution, with source/plan/input hashes and required completion keys. Extend only when a failure or a newly reviewed claim justifies more cases. In the wrong-neighbor control, all three native plans may agree with one another but must fail the source oracle. Altered-first-invalid uses an invalid-input case; truncation must remove bytes from the final chunk, not merely empty a header.

- [ ] Run portable manifest/fault tests first:

      PYTHONPATH=src:research python -m unittest discover -s research/tests -p test_large_correspondence.py -v

  Expected RED before implementation: missing command or rejected incomplete manifest not yet enforced. Portable tests use retained fixture transports; they make no native claim.

- [ ] Implement the command around build_native_v2(emission, qualification, *, limits) and invoke_native_v2(build, invocation, *, limits), then O5 acquisition/comparison. Keep exact Core same-source evidence distinct from cross-plan Axiom state comparison. Do not claim a large reference/IR lane if it does not admit the profile.

- [ ] Execute the explicit native campaign:

      PYTHONPATH=src:research python -m large_correspondence --manifest PATH_TO_FROZEN_MANIFEST --qualification PATH_TO_QUALIFICATION --out NEW_OUTPUT_DIRECTORY

  Expected GREEN: exit 0, complete manifest keyset, every valid case matches the independent source state, every invalid case preserves initial output and reports the correct first failure, all fault controls reject for their intended reason, and no required cell is skipped. Save command, actual counts, toolchain/source hashes and failures. This is a correctness run; no speedup claim or admitted timing is produced.

- [ ] Independently review the exact complete campaign and all deliberate faults; commit implementation and small reproducible manifests, retaining bulky evidence in the declared stores. Commit message: test(axiom): establish independent large native correspondence.

**Stop:** If Core large-buffer admission, complete capture, oracle completion or cleanup fails, report the exact unavailable gate and preserve evidence. Do not replace Axiom/Core with a handwritten C stencil or raise v1 limits to make this milestone appear complete.

## Completion evidence and handoff

O6 delivers the first meaningful larger stencil demonstration. The implementation record must name actual source/profile/plan/Core/collector/oracle identities; enumerate complete/failed/unavailable cells; give exact retained-store budgets and logical-work totals; link review dispositions; and retain trusted parser/runtime/OS/hardware assumptions. Plan 04 may open native measurement only after its own instrument/resource/chronology gates pass. Source/native correctness alone does not qualify performance.
