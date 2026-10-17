# Scalable Axiom execution: shared design

Date: 2026-10-16. Confidential planning artifact. This specifies proposed work; it does not record implementation or new benchmark results.

## Goal and scope

Take the existing canonical integer stencil beyond the 256-input-cell prototype while preserving its precise scalar and rejection semantics. A programmer still declares the computation and a resource constraint. Axiom produces a compact physical plan; an independent checker establishes its eligibility; Core executes the admitted plan on runtime buffers; an independent source interpreter checks the complete observed result.

The first acceptance target is all three schedules on disclosed development shapes, progressing to W=2048/H=2048. That shape has 4,198,401 input cells and 4,194,304 output cells. A full semantic state is 33,570,820 bytes. This milestone does not require a performance win. A qualified experiment and an identifiable research contribution are subsequent gates.

Core is Beryl's normal 4GL compiler. Axiom is the separate, confidential 5GL research project. This milestone investigates one narrow declarative language profile; it does not establish general 5GL synthesis. Runtime input values are dynamic; dimensions are specialized source constants. General symbolic shapes, arbitrary constraints, floating point, reductions, GPU execution, parallel scheduling and a public foreign-pointer ABI are outside this milestone.

## Baseline and evidence status

Inspection baseline:

- Lattice: `1011eea5edf0bd13208409e385a9b77c43adbc57`.
- Core: `0a678b4ae6d41190c4f5a8bf063caba05759d20d`.
- Existing portable correctness suite: 115 tests; all 955 admitted shapes and 2,865 shape/plan specializations covered in the retained implementation record.
- Existing research suite: 86 tests, also exercised under optimized Python.
- Retained actual correspondence campaigns: 1,620/1,620 cells each, including 1,296 native cells; 45 rehashed faulty-emitter controls were detected independently.
- Core has exactly two known failures among 10,814 checks/583 cases in `IR: initialized SET destination remains readable during later scalar capture`. Qualification records this baseline; it does not call the suite green.
- Native performance admission is currently unavailable. Existing native witnesses embed fixed cases; they do not supply the reusable buffer ABI proposed here.

These are inherited results documented in [implementation-record.md](../../../implementation-record.md) and the retained implementation review, not tests rerun while writing this plan. Source inspection supports trying production Core Lists; actual scalable execution remains to be demonstrated. Fresh-task restoration of local work and publication of the cloud configuration draft remain unverified.

## Architectural choice

| Option | Result | Decision |
| --- | --- | --- |
| Existing Core production AST backend, `List<i32>` borrows, private host-owned storage | Uses existing checked lowering and avoids relying on unsupported reference/IR List execution | Preferred; qualify with tiny fixtures before constructing the whole pipeline |
| Narrow Core export/header or buffer-admission change | Can repair a demonstrated binding/admission deficiency | Authorized conditional route, in a separate reviewed Core change and explicit new backend profile |
| Direct C implementation | Useful matched control and collector calibration | Does not satisfy Axiom-through-Core acceptance |
| Raise existing finite-plan/IR size limits | Retains unrolling and misses List/reference limitations | Rejected as the scalability architecture |

The preferred dataflow is:

```text
retained source bytes ── explicit scalable source admission
         │                         │
         │                  untrusted plan + certificate
         │                         │
         │                  independent fresh checking
         │                         │
         │                    Core source emission
         │                         │
         │              Core emit-c + qualified host build
         │                         │
verified invocation ───── owned checked native call
         │                         │
original-AST oracle         full post-call acquisition
         │                         │
         └───── complete byte comparison ──────┘
                              │
                 versioned native evidence admission
                              │
                    frozen statistical evaluation
```

Planner, certificate producer and selector are untrusted. The checker must not import or dispatch on their implementations. The oracle must not import the checker, planner, selector, emitter or native computation. Sharing parser/AST records and serialization is permitted and explicitly part of the common trusted base.

## Source, arithmetic and identities

The new source profile is `axiom-stencil-fixed-buffer-v1`:

```text
1 <= H,W <= 8192
P = (H+1)*(W+1) <= 2^23
O = H*W
input: i32[P], admitted values 0..1023
producer(r,c) = (input(r,c)+1) * (input(r,c)+1)
output(r,c) = ((producer(r,c)+producer(r,c+1))
                +producer(r+1,c))+producer(r+1,c+1)
```

The actual parsed AST, including association, governs computation. The equations above describe the currently supported normalized family. Every source and physical scalar operation uses checked i32 semantics. Producer values are 1..1,048,576; successive output sums are bounded by 2,097,152, 3,145,728 and 4,194,304. Dead operations are still checked and counted. Mathematical index analysis must separately prove that generated i32 arithmetic and checked host byte arithmetic fit their machine domains.

The dimension/cell caps are proposed engineering admission limits, not a language theorem or native memory promise. They cover the existing corpus and leave room for independent scaling controls. The execution profile also requires `0 <= scratch_capacity_cells <= P`, even for hand-authored plans; unused capacity still counts. One complete semantic state is strictly below 64 MiB, and reserved plan scratch is at most 32 MiB. Actual memory/work/evidence budgets remain separate.

On source precondition failure, the result identifies the first invalid input index in canonical row-major order. The complete input and original output remain unchanged. No scratch allocation, scratch initialization or body execution precedes this decision. Only success and input-precondition failure are completed semantic states. Invalid handles, native resource failure, traps, timeout, cancellation and missing acquisition have separate execution-failure records.

Use three distinct identities:

1. `source_sha256`: exact retained bytes, including names, spelling and formatting.
2. `family_semantics_sha256`: versioned canonical shape-independent equations, tensor roles/types, scalar arithmetic and boundary semantics. Alpha-normalize bound names; exclude literal H/W values and optimization preferences. Include the source-profile semantics version. Do not treat arbitrary ASTs as the canonical family.
3. `specialization_semantics_sha256`: family identity plus exact H/W and the versioned specialization contract.

Source constraints and objective have their own canonical identities and effective-cap intersection. They must remain bound to checking/replay even though they are not the value semantics. Source ordering/path fingerprints, generated C, binaries, compiler pins, plan bytes, certificate bytes and execution instances have separate identities. Never substitute one for another. V1 byte formats, hashes, admission limits and replay behavior remain unchanged.

## Shared implementation interfaces and ownership

All paths below are proposed under the repository root. Subsystem plans define their details once; other components consume those public contracts.

| Owner | Module / interface | Result and obligations |
| --- | --- | --- |
| C2 | `axiom/src/axiom/source_profiles.py`: `admit_source_v2(source_bytes, *, profile, limits)` | Immutable `AdmittedLoopKernel`, exact source/family/specialization identities, AST, H/W, effective source constraints; public callers re-admit bytes |
| C3–C5 | `loop_model.py`, `loop_codec.py`, `loop_regions.py`, `loop_checker.py`: `check_loop_plan(source_bytes, candidate, *, constraints, limits)` | `LoopCandidate(plan_bytes, certificate_bytes)` → `LoopCheckResult`; proof status, semantic status, constraint status, exact complete metrics, work and identities |
| C8–C10 | `loop_planner.py`, `loop_selection.py`, `loop_evidence.py` | Three untrusted producers, deterministic charged selection, immutable selected tuple, exact replay with fresh checking |
| B4 | `loop_core_emit.py`: `emit_loop_core(source_bytes, candidate, *, constraints, limits)` | Fresh-checks; returns `CoreEmissionV2` binding source/plan/certificate/Core text/origin map; saved receipt alone grants nothing |
| O1 | `axiom/src/axiom/invocation_v2.py`: `verify_invocation(manifest: Path, *, limits)` | `VerifiedInvocation` binds source/shape/profile and complete original input/initial output; immutable handles are not a substitute for revalidating bytes at trust boundaries |
| B5 | `core_native_v2.py`: `build_native_v2(emission, qualification, *, limits)` | `NativeBuildV2` binding compiler/runtime/host/generated bytes, argv, executable and evidence roots |
| B3/B6 | `core_native_v2.py`: `invoke_native_v2(build, invocation, *, limits)` | `NativeRunV2`, completed semantic status or typed execution failure, unique invocation identity and actual acquisition references |
| O2 | `axiom/research/source_oracle.py`: `evaluate_source_state(source_bytes, invocation, destination, *, profile, limits)` | `OracleResult`: complete expected state only for completed source evaluation; quota/infrastructure failures remain unavailable |
| O5 | `native_acquisition.py`, `state_store.py` | Full post-call byte acquisition and comparison before semantic state sharing; unique receipts per invocation |
| Plan 04 | `native_contract.py`, `collector_qualification.py`, `native_collector.py`, `native_receipt_admission.py`, `native_evaluate_adapter.py` | Versioned native qualification and admission, full closure validation and frozen evaluation; no synthetic-to-native relabeling |
| I1 | `axiom/src/axiom/scalable_cli.py` | Explicit v2 plan/check/replay/compile commands; old CLI behavior remains unchanged |

Do not place a second native allocator or driver in research. The common host/allocator lives in `axiom/native/v2/`; research controls it through the public native API. Production transport types must not import research oracle/evaluator code. Keep schema ownership explicit before parallel implementation begins.

`NativeQualification` belongs to B5's `core_native_v2.py` and extends the revalidated existing `core_toolchain.Toolchain` with build-route contracts/inventory. It is distinct from M2's later reviewed measurement `NativeCapability`; neither record can manufacture the other. Source-profile records resolve the fixed registered profile and may tighten operational limits, but caller-provided altered maxima cannot widen the admitted profile merely by retaining its identifier.

## Compact proof boundary

Plan v2 contains bounded structured loops, typed input/scratch/output accesses, scalar constants/add/mul, and stores. Index terms are affine after shape specialization with literal modulo two. Index/control terms cannot carry scalar payload, read tensor data or cast retained data into uncharged metadata. There are no data-dependent branches, calls, arbitrary pointers or loop-carried scalar SSA. Scalar loop-local values do not escape an iteration; retained data crosses iterations through declared scratch.

The certificate is a bounded untrusted proof DAG. The checker reconstructs original source terms and checks each affine bound, substitution, rectangle split/join, initialized-region fact, disjoint frame, exact scalar expression and induction step. Output-written regions have linear conservation: forgetting a scratch fact is permitted; forgetting a write and then accepting a duplicate is not. Modulo-two reasoning uses exhaustive bounded parity cases. No generator-supplied assertion becomes an axiom.

The initial soundness statement is conditional: for a fixed admitted source specialization, a verified certificate implies every admitted input produces the exact source output, input remains unchanged, every access is in bounds, every scratch read is initialized, and every output is written exactly once, assuming the specified proof rules are correctly implemented. Review a written proof argument and implementation mapping. Do not call this machine-checked formal verification unless a corresponding mechanized theorem actually exists. This theorem does not verify the downstream Core/C compiler; native correspondence tests address that gap empirically.

For rows2, stage producer row zero once. On iteration r, stage row r+1 into parity slot `(r+1)%2`, then consume current and next rows. The invariant states that the current row is initialized with the source producer and output rows `[0,r)` are complete. Distinct parity slots preserve the current row during refill. This avoids an unchecked refill branch and covers H=1/W=1.

Missing, unsupported or failed proof gives semantic `unknown`, not evidence that the plan is false. A semantic `invalid` result needs a checked concrete witness or a demonstrably invalid structural effect. Fuel exhaustion is incomplete; completed independent metric passes may retain their results, but partial work must not masquerade as exact whole-plan metrics. Eligibility requires verified proof, valid semantics, satisfied constraints and complete checking.

Checker cost must depend on bounded syntax/proof size and bounded integer widths, not expanded H×W execution. The checker must succeed on large shapes without allocating input/output buffers. Hand-authored plans, alpha-renaming, independent operation order and alternate legal traversals must establish that acceptance is rule-driven. Stop if rows2 checking requires trusting a generator or expanding all iterations.

## Resource contracts

Preserve `plan_workspace_bytes = 4 * reserved_scratch_cells`. This counts unused reserved arena cells but excludes retained SSA and native memory. Dynamic operation counts come from actual IR structure, including dead work, not schedule labels.

A separately reviewed optional property is `abstract_storage_bytes-v2 = 4 * (reserved_scratch_cells + peak_transient_live_i32_SSA_cells)`. The abstract machine allocates a result before retiring last-use operands and retires a dead result immediately afterward. Scratch remains reserved for the body. Typed indices/control metadata, input/output and native stack/heap/spills are excluded. Loop summaries must handle empty/single/multiple trips without iteration expansion. The retained zero-arena SSA-staged control must be counted honestly. Defer this hard constraint if exact compositional liveness is not ready; do not silently broaden the arena claim.

Native allocation measurement is a third, separate quantity: operation-owned requested heap bytes and lifetimes, including every reachable allocation path in that scope. Peak live bytes, retained bytes after cleanup and allocation count require actual instrumentation. RSS, executable text, caller buffers, allocator overhead and stack/spills are separately identified. None of these quantities can substitute for another.

## Native checked entry

The initial ABI is private `axiom-core-buffer-host-v1`, on the qualified Linux/x86-64 target. It accepts host-owned, live, generation-checked input/output handles with exact initialized extents and separate allocations. It is not an arbitrary raw-pointer validator or hostile-code sandbox.

The measured checked call performs, in order:

1. Validate fixed specialization, handle generation/liveness, extents, initialization and disjoint allocation identities.
2. Execute the ordinary Core preflight helper in row-major order.
3. Return source rejection if invalid, without scratch setup/body.
4. Allocate exact scratch, zero-initialize it, and create actual generated Core List descriptors; inline uses `{NULL,0,0}` without a pretend allocation.
5. Execute the Core body using checked scalar operations, get/set and range loops. Prohibit growth, descriptor replacement, escape and owning local Lists.
6. Check descriptor integrity and perform scratch cleanup; finish the checked-call timer.
7. Acquire the entire actual post-call input/output and status outside the timer, then independently compare it. This extra full scan is collector work, not hidden in the primary timing.

Input is immutable between preflight and body under exclusive host ownership and synchronous invocation; there are no views/callbacks/concurrent mutation. Recoverable allocation failure before the body preserves output but is an execution resource failure, not a source result. Crashes/timeouts do not receive successful cleanup or complete-state receipts.

Use the actual emitted List typedef and deterministic pinned symbols, compile-time signature/layout assertions and unchanged generated C. Do not reinterpret a lookalike struct or patch emitted C by regex. Existing Lists lack complete automatic scope-exit cleanup; `clear` does not free and current `defer` is immediate. The host owns cleanup explicitly.

Logical eligibility and native lowerability are separate. The IR uses nonnegative i32 loop bounds with a representable terminal counter, while affine proof arithmetic may use bounded wider mathematical integers. Prove every emitted index/control intermediate fits its machine type, including linearization and increments. A canceling expression such as `K*r-K*r+c` may have an in-range normalized address while naive evaluation overflows. Emit an independently bounded equivalent expression or return `NativeLoweringUnsupported`; do not relabel a logically valid plan semantically invalid. Preserve Euclidean modulo semantics, including rejecting unsupported negative-argument lowering instead of silently using C's different remainder behavior.

If this seam fails, retain the smallest reproducible failure and assess a narrow Core export manifest/header or admission patch in a separate review. Do not turn this fallback into general ownership repair, slices, IR productionization or an unchecked alternative. Requalify the new Core pin explicitly; never loosen old pin checks.

## Oracle, evidence and budget boundaries

The oracle reparses source bytes and interprets the original AST with Python integers and per-node i32 checks. It streams output and uses bounded immutable chunk access to input, without reproducing the native circular schedule. Full preflight precedes equation evaluation. Its cache/heap/work/elapsed limits are explicit; mapped storage does not imply constant RSS. An exhausted oracle yields no expected result.

Reuse state-v1's signed little-endian i32 encoding for completed states without changing its semantics. Native v2 adds acquisition, comparison and execution-failure records. Every invocation must actually acquire all post-call bytes and traverse them in a complete comparison. Hashes identify objects; they do not replace those traversals. Only after complete comparison may identical states share retained CAS bytes. Run/acquisition/comparison identities remain distinct.

Separate coordinated stores:

| Store | Proposed limits | Admission |
| --- | --- | --- |
| Semantic | 256 MiB unique closure per independently admitted stratum capsule; 16 MiB per file; 1 MiB chunks; 16,384 files | Complete actual states, acquisition/comparison, experiment/measurement records and executable bindings |
| Qualification | 512 MiB unique closure; 16 MiB per file; 1 MiB chunks; explicit file/metadata limits | Typed blob manifests for actual compiler, configuration, runtime, linker/SDK inputs and reviewed implementation dependencies |

Both roots are fully traversed and bound by native admission. The bounded analytical evaluator receives one stratum's semantic view and qualification identity; outer admission validates all qualification bytes. A bounded campaign index binds at most 256 admitted stratum roots and their shared qualification root. Proposed campaign budgets are 8 GiB retained semantic bytes, 131,072 total semantic files, 1 GiB failed-run quarantine, 256 MiB temporary acquisition storage with one acquisition worker, and 1 TiB cumulative logical I/O. Calculate actual unique stored paths and all repeated acquisition/comparison/revalidation work before launch; equal bytes at different paths count twice. Splitting roots cannot bypass the campaign caps, sample identity or complete stratum admission. These are proposed explicit v2 engineering budgets, not v1 extensions.

Inventory before execution: the currently known 17 compiler components already total 237,929,136 bytes, and several exceed 16 MiB individually. Chunking changes representation, not aggregate accounting. If the complete declared inventory exceeds a quota, stop unavailable; do not omit dependencies or silently widen v1.

Per-invocation state size, unique retained closure, cumulative acquisition bytes, comparison read bytes, oracle work and temporary disk use are separately bounded. Repetition cannot disappear through deduplication. For example, 32 pilot pairs plus 32 final pairs entail 128 executions for a stratum; at the historical primary, actual observed semantic bytes alone total 4,297,063,936. Capture/comparison overhead and environmental hardware honesty remain explicit trust boundaries.

## Experiment and claim boundary

The existing primary and at least one exact thin held-out fixture have been exposed during development. Preserve the access history and original protocol. Use the old corpus descriptively. A future confirmatory claim needs a distinct preregistered experiment, audited new holdout shapes and a frozen selection/analysis procedure. A new seed does not restore shape independence.

Required baselines are the straightforward checked scalar Core implementation, each fixed compact plan, analytic selection, and best fixed plan chosen on training only. Retain SSA accounting controls and v1 overlap. For an external claim, prioritize the exact Halide stencil and Exo's checked scheduling; match semantics, boundaries, target and paid work.

Qualified performance includes full checked-call setup/preflight/allocation/initialization/body/cleanup. Inner-kernel, process, capture, oracle and compilation times are separately reported. Sampling uses the frozen balanced AB/BA paired design, not a mislabeled four-run block. No adaptive stopping, discarded slow samples or pooling unrelated strata. Preserve all failures and null results. Full statistical details belong to plan 04.

An internal technical report can document actual existing results immediately. A scalable engineering report requires real native execution and full independent correspondence. A paper requires a defensible contribution beyond known scheduling/validation/storage techniques; performance or general-language claims need additional evidence. Public disclosure requires review of the actual manuscript/artifacts because the user designated Axiom secret. This plan authorizes neither publication nor messages to external researchers/models.

## Cross-cutting invariants for every review

- No v1 admission/hash/native-eligibility changes hidden inside v2 work.
- No trusted generator, forged proof success, scalar-in-index storage escape, or silently unrolled checking.
- No native result without actual complete observed state and independent source comparison.
- No expected bytes substituted for observed bytes, hash-only correctness or dedup-discounted acquisition work.
- No semantic failure manufactured from resource, capture, quota or process failure.
- No universal native-memory, global-optimality, general-language or novelty claim from this narrow prototype.
- No stale receipt authority, missing transitive evidence silently omitted, or unknown metric filled with zero.
- No erasure of dataset exposure, invented chronology or external disclosure during implementation.

Subsystem plans and the master acceptance gates operationalize these invariants. Any proposed interface/contract change updates this design first, then its tests and dependent plans; implementation convenience cannot silently redefine the claim.
