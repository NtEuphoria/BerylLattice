# Axiom proof/oracle continuation: implementation plan

> Required execution workflow: Superpowers subagent-driven development, meaningful RED/GREEN checks, independent review and verification before completion. User authorization already includes planning and implementation. This plan records dependencies and gates, not another approval request.

**Goal:** Make the immediate blockers to checked scalable execution concrete: complete constructive C1 evidence and an independently executable original-source oracle. Continue into dependent checker/native work only when its existing prerequisites are actually satisfied.

**Design:** [Continuation contract](../specs/2026-10-16-axiom-proof-oracle-continuation-design.md), subordinate to the [reviewed scalability master plan](2026-10-16-axiom-scalability/README.md). Python standard library research code; existing C2/O1/state dependencies. No new package or Core change required.

**Baseline:** `2e827dacf2b6ece9640df7abdf43a74892d9fc9f`; Core `0a678b4ae6d41190c4f5a8bf063caba05759d20d`. Existing C2/B1/B2/O1/B3 remain accepted. C1/F1 remains blocked. v1 behavior and fixed quotas stay unchanged.

## Task graph and ownership

| Task | Prerequisites | Sole owned files / interfaces | Completion evidence |
|---|---|---|---|
| P0 plan preflight | design advice | this plan and continuation spec; controller | independent consistency/interface table; addressed findings |
| P1 constructive C1 | P0 | `axiom/research/loop_proof_graph.py`, `loop_proof_cost.py`, `fixtures/loop_proof_obligations.json`, `tests/test_loop_proof_graph.py`, `tests/test_loop_proof_cost.py`; existing `loop_proof_feasibility.py`, its test, and `axiom/docs/loop-plan-v2.md` | complete exact graphs, obligation mapping, encoding/accounting envelope argument, adversarial controls, focused normal/-O logs |
| O2 source oracle | P0; accepted C2/O1 | `axiom/research/source_oracle.py`, `tests/test_source_oracle.py`, `protocol/source-oracle-v1.md` | original-AST execution, complete state controls, failures/publication boundaries, normal/-O logs |
| P2 C1 acceptance | P1 immutable checkpoint | controller owns `docs/reviews/loop-proof-feasibility.md`; fresh reviewer writes separate report | independent mathematical/implementation review of complete artifact hash closure; explicit proceed or precise blocked finding |
| O2R oracle acceptance | O2 immutable checkpoint | fresh reviewer report; fixes returned to O2 owner | independent semantic/dependency/resource/quality review, focused reruns |
| A0–A3 deterministic source names | demonstrated C2 lookup-cost gap; [repair plan](2026-10-16-axiom-bounded-source-admission.md) | separately reviewed v2-only adapter/source-profile files and tests; disjoint from P1/O3 | accepted-language/identity preservation, actual bounded name algorithm, dependency reruns; no implicit C1 approval |
| I0 integration checkpoint | P2/O2R and A3 dependency reconciliation | controller implementation record, recovery/index/startup notes as needed | combined regressions, immutable reviewed commits, recoverable code/evidence |
| downstream execution | positive required gates | exact master-plan owners C3–C11, B4–B7, O3–O6, I1 | acceptance evidence from each named master task; no implicit qualification |

P1 and O2 may run concurrently because they share only immutable dependencies. The controller serializes documentation integration, commits and shared API changes. Neither implementer edits the other's files, the tracked acceptance record, Core or old v1 implementation. Independent review may inspect shared dependencies but must distinguish pre-existing findings.

The later A0–A3 amendment repairs the actual C2 source-name algorithm before a positive source-work bound can be claimed. Its new C2 revision requires fresh O2/O3 dependency checks; their prior approvals remain historical to their pinned checkpoints. The original frontend/v1 bytes remain unchanged.

## P0: verify the plan before coding

1. Read the two design-advice reports and relevant master tasks. Preserve the actual unresolved F1 finding rather than treating the earlier loose bound as impossibility.
2. Self-check every task's inputs, outputs, failure states, test commands and ownership. Obtain a fresh independent preflight with a row per task and per shared interface/file pair. Resolve concrete contradictions in these two documents before dispatching implementation.
3. Record rulings in `.superpowers/sdd/axiom-checked-execution/progress.md`; retain briefs/reviews/logs there. Commit only the two named design/plan files.

## P1: complete constructive compact-proof evidence

### P1a: explicit representation and independently enumerated obligations

1. Read the normative rule/theorem/hand derivations and current F1 appendix. Write the experimental typed row grammar, including scopes/binders, indices, terms, substitutions, closures, regions, scalar environments, complete states and proof transitions. Exact plan bytes separately encode all ordered operations and layout/capacity.
2. Build an obligation manifest from the written rules, not from the implementation's category dictionary. Identify every source reconstruction, physical operation, source equality, bounds/initialization/frame premise, full-ledger transition, induction base/step/exit, parity premise and scope discharge.
3. Preserve source origins and distinct binder namespaces. Source closures retain formal binders and explicit coordinate maps. State IDs and block cursors enforce order and multiplicity; equality of coverage sets is insufficient.
4. Retain the existing research-only `run_feasibility()` boundary. Add `construct_hand_derivation(source_bytes, outline)`, `encode_hand_derivation(derivation)`, `enumerate_work(derivation, accounting_spec)` and `bound_hand_family(outline, source_envelope, accounting_spec)` with immutable structured outputs. These APIs construct/describe examples; they confer no arbitrary-candidate eligibility.

### P1b: exact construction and meaningful tests

1. First add failing tests for all three complete graph inventories, actual state links, source closure scopes and exact canonical encoding. Retain the failure log before implementation.
2. Instantiate inline, materialize and rows2 without loops over H/W/P/output cells. Reconcile primitive instances 20/13/31, induction instances 2/4/6 and physical node counts 22/17/22, without hard-coding the larger proof inventory.
3. Include all transient states: scratch singleton before join, complete incoming output ledger, real producer-to-consumer/refill-to-consumer links, both parity contexts and successor states. Count each typed payload/reference and actual row width.
4. Preserve actual AST reconstruction and ordered scalar association. Derive actual term reachability rather than declaring the suggested 31/34/55 counts successful. Explain any deviation.
5. Mutation controls: omitted/reordered/dead operations; disconnected state edges; reset output ledger; omitted base/incorrect successor; escaping hypothesis; capture or wrong substitution scope; incompatible closure/map join; missing/duplicate parity case; overlapping ring rows; changed input coordinate/scalar association/origin.

### P1c: fully charged work and envelope

1. Implement charged bounded arithmetic and deterministic exact-key lookup accounting. Every event identifies its owner/call site, inputs/widths, structural and integer work, and memo result where applicable. No random-hash average-case assumption establishes a deterministic bound.
2. Enumerate actual reachable substitution/ordered comparison keys. Charge cache hits, exact-key comparisons, scope checks and state/ledger operations. Source, plan and certificate identity traversals and serialization are included under an explicit byte-work policy; decoder ingestion limits remain separately identified.
3. Audit the actual frontend/profile identity algorithms and bind that audit to their code identities. Prove a conservative bound over accepted source spellings, groups, repeated constraints and identifier/token sizes. Missing source-phase accounting leaves F1 unresolved.
4. Derive a finite constructor recurrence and per-call-site integer bounds over `1<=H,W<=8192`, `(H+1)*(W+1)<=2**23`. Include -2**31's 32-bit magnitude. Use relational P bounds where necessary; label enclosing boxes as conservative bounds.
5. Produce a table of every fixed quota with concrete counts/bytes and justified envelope bounds: source, plan, certificate, IR, scalar definitions, loop depth, affine terms, active facts, region pieces, proof nodes, parity cases, symbolic nodes/depth, integer width and total work. Exact bytes are serialized artifacts, not an event-log size estimate.
6. Controls remove events from each independent manifest family; exercise equal-prefix key comparisons, shared DAGs, differently scoped substitutions, exact limits/limit+1 and source-spelling extremes. Quota exhaustion is incomplete; no counter overrun is accepted.
7. Corroborate `(1,1)`, 32/128/512/2048 training squares and `(8191,1023)`, `(8192,1022)` plus transpositions without tensor allocation. Numerical samples are not the envelope proof.

### P1d/P2: verification and acceptance

Run from `axiom/`:

```sh
PYTHONPATH=src:research python -m unittest discover -s research/tests -p 'test_loop_proof*.py' -v
PYTHONPATH=src:research python -O -m unittest discover -s research/tests -p 'test_loop_proof*.py' -v
```

Fresh review examines both completeness and accounting against the written theorem and exact diff. Reviewer is neither the design adviser nor implementer. Retain exact artifact hashes, commands and unresolved findings. The controller updates the tracked gate only after review, explicitly expanding its hash contract to every construction/accounting helper and fixture. Passing these tests alone never sets `proceed`. A blocked result requires a precise missing obligation and investigation of a constructive repair; no silent quota/profile relaxation.

## O2: implement independent original-AST evaluation

### Contract and records

`evaluate_source_state(source_bytes: bytes, invocation: VerifiedInvocation, destination: Path, *, profile: SourceProfileV2, limits: OracleLimits) -> OracleResult`.

`OracleLimits` fields: `max_source_bytes=65536`, `max_cached_input_bytes=2097152`, `max_scalar_evaluations=1000000000`, `max_temporary_bytes=268435456`, `max_input_snapshot_bytes=33554432`, `state_limits=ArtifactLimits()`, optional exact-integer `deadline_monotonic_ns`, optional cancellation callable. Validate exact types and nested ceilings at entry; limits only tighten. Document minimum aligned cache chunk behavior.

`OracleResult` fields: status; optional state manifest and first-bad index; exact source/family/specialization/v2 invocation/state-v1 invocation identities; `scalar_evaluations`, `input_preflight_scalars`, `emitted_state_scalars`, `input_read_scalars`, `input_snapshot_bytes`; bounded failure detail. Optional additional counters must have narrow observable units documented in the protocol. Only success and input-precondition failure are complete states. No caller-created result is trusted qualification.

### Implementation order

1. Write a failing independent 1×1 test (`[0,1,2,3] -> [30]`) and invalid-input canary preservation test, then preserve RED output.
2. Implement source admission and invocation revalidation/identity matching. Distinguish unsupported source, mismatched/invalid invocation and later operational failure.
3. Compute shape-specific logical temporary payload reservation before creating/acquiring streams. Do not assume deduplication. Preflight the conservative chunk count plus manifest file, individual file lengths, metadata bound and aggregate/logical state bytes against tightened state quotas before acquisition/writes: the existing state writer checks file/aggregate limits only in final verification. Classify disk-full/write failures explicitly. Do not claim physical disk or RSS reservation.
4. Exclusively reserve destination safely. Acquire verified input into an anonymous snapshot, full length/hash verification and row-major preflight; carry at most three bytes across split i32 chunks. Record first invalid index but finish scanning.
5. Implement bounded snapshot cache with aligned chunks, pre-allocation eviction and checked exact-length `pread`; never retain producer/output-sized containers. Stream preserved input from this snapshot.
6. Implement original-node visitor with checked i32 at every node, original order/groups, declared names/bounds and lazy producer declaration evaluation. Charge AST fuel before dispatch. Preserve resource failures distinctly. No equation visitor is called for rejected input.
7. Stream complete state through existing `write_state` in a private pending child. Invalid input streams original initial output. Verify the state, compare explicit invocation identity mapping, revalidate the original invocation and poll deadline/cancellation before atomic publication. Clean up owned partial artifacts/handles on all precommit failures. Do not overwrite an existing destination or relabel a committed artifact after publication.
8. Document cooperative polling points and opaque helper passes. Result counters are not complete campaign I/O accounting. Preserve the narrow supported family and shared frontend trusted base.

### Test matrix

Compare the full state/status/first-bad index to the existing independent small reference only within P<=256: boundary corpus, 1×1, 5×7 coordinate case, every invalid position in 2×3, -1/1024/i32 extrema, nonzero output canaries, alpha renames and grouping variants. Do not widen the v1 comparator.

Use disclosed 32×32 all-zero/all-max correctness controls: each output is respectively 4/4,194,304. Verify all P+O values, identities and byte preservation. Exercise blob chunks of 7 bytes, aligned state chunks of 16 bytes, tiny tightened cache and cache eviction/first/last values.

Prove dependency independence with inspection and a clean subprocess import guard. Group-only source changes must increase AST work while preserving results; +1→+2 is unsupported. Exact measured work budget succeeds and one less fails incomplete. A patched equation visitor must remain uncalled on rejected input.

Exercise forged typed invocation fields; mutation before acquisition and immediately before publication; cancellation early/mid-preflight/mid-output/prepublish; expired deadline; MemoryError; snapshot write/short-read failure; state chunk/verification failure; tight logical/aggregate/metadata/file/temporary quotas; existing destination preservation and complete cleanup. No unrelated programmer exception becomes a semantic rejection.

Run from `axiom/`:

```sh
PYTHONPATH=src:research python -m unittest discover -s research/tests -p 'test_source_oracle.py' -v
PYTHONPATH=src:research python -O -m unittest discover -s research/tests -p 'test_source_oracle.py' -v
```

Then run relevant reference/source-profile/blob/invocation/state regressions. Fresh independent review checks semantics, declaration interpretation, publication boundaries and bounded resources at an immutable checkpoint. Return concrete findings to the same implementer and rerun affected checks.

### Scale qualification, not speed claims

Record complete 32×32 oracle wall time and AST/cache/observable byte counts; if affordable, repeat 128×128. The current canonical source takes approximately 77 AST visits per output plus declarations, so 2048² implies roughly 323 million visits. Use actual measured throughput to choose a finite supervised budget before a larger disclosed training run. Do not omit semantic checks, change AST grouping or run fresh held-out data to improve timing. O3 remains necessary before these results become an oracle trust anchor.

## Downstream implementation gates

Once P2 is positive, execute the master tasks in dependency order with their exact tests and reviews: C3 schema reconciliation/codec; C4 generic rules; C5 actual-plan induction/source checker; C6 independent concrete/v1 bridge; C8 untrusted generators; C9 selection and C10 replay. C7 optional abstract-storage accounting stays separately gated. C11 demonstrates structural scaling without unrolling.

B4 emission must freshly call the accepted checker; B5 binds exact toolchain/source/emission and B3 ownership; B6 executes only owned qualified buffers. In parallel after reviewed O2, O3 qualifies exact oracle/runtime/tests/review, O4 owns evidence stores, O5 captures/compares every complete call and O6 performs the single G3 campaign. B7 consumes that same campaign. I1 exposes the checked route only after its declared prerequisites.

No downstream step can consume a placeholder success, unverifiable receipt or incomplete metric. If P2 stays blocked, continue useful independent O2/O3 infrastructure and repair the specific proof gap, while preserving the native gate. The milestone report must distinguish implemented, reviewed, executed and still blocked work.

Measurement proceeds only after G3/G4 and complete instrument qualification. The master freeze/holdout/publication chronology still applies. No performance or scientific novelty conclusion follows from oracle throughput or compact graph sizes.

## Final integration and recoverability

Run appropriate complete product and research suites once at the integrated checkpoint, preserving explicit native/nightly skips and known baseline failures. Run native checks only if changed/native-dependent work requires them. Verify unchanged v1 files and Core, review the final diff, retain exact commits and reviewed artifact hashes.

Update the implementation record with actual outcomes and remaining gates. Save and verify a complete Git recovery bundle and retained review/test evidence; check restoration of changed files. Update reusable cloud setup instructions only when the workflow actually changes. Saved configuration is not published configuration or proof of a fresh-cloud restore. Do not publish papers, contact collaborators, push shared branches or merge on the strength of this local implementation request.
