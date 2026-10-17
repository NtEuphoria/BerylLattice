# Axiom: complete compact derivations and an independent source oracle

Date: 2026-10-16. Starting checkpoint: `2e827dacf2b6ece9640df7abdf43a74892d9fc9f`.

The next useful result is an execution whose source meaning, compact proof and complete observed state can be checked independently. The [scalability architecture](../plans/2026-10-16-axiom-scalability/design.md) remains authoritative. This continuation makes its two immediate prerequisites concrete: resolve C1/F1 with complete derivations and implement O2's original-source calculator. It does not replace the roadmap with another prototype architecture.

Core remains the ordinary 4GL compiler. Axiom remains the separate experimental 5GL project. The first admitted computation family, source semantics, v1 interfaces, proof quotas, native ownership requirements and publication gates remain unchanged. Core modifications require demonstrated need and separate review; this milestone needs none.

## Compact derivations

The previous 8,814,588-unit estimate reserved uninstantiated tables and charged most term entries as expensive multiplication. It is neither a complete certificate nor evidence that compact checking is impossible. We will construct every table and account for its actual operations.

The representation uses ordered scalar DAGs, typed affine indices, distinct binder identities, explicit substitutions, scoped region value closures, immutable state records and ordered proof transitions. Source producer/output functions are reconstructed from the retained original AST; they are never trusted producer opcodes. A region refers to a reconstructed value function with capture-free coordinate substitutions. Extending a rectangle's endpoint does not copy its value expression. Pure expressions can share representation; effects, hypotheses and case-specific propositions retain their scope and ownership.

For the proposed constructor, the open output expression has 16 scalar nodes, including constant 1. Inline adds 15 coordinate-dependent nodes; materialize adds 3 producer and 15 consumer nodes; rows2 adds 3 initial producer nodes and two parity cases with 3 producer plus 15 consumer nodes each. The resulting 31/34/55 counts are design ceilings for scalar values alone, conditional on that construction. They are not total proof counts, measured results or quota acceptance.

Every primitive operation must appear in an ordered physical coverage spine. Each transition consumes the actual incoming scalar/scratch/output state and supplies the next transition. Induction explicitly represents base, arbitrary iteration, body, successor equality, discharge and exit. All three schedules conserve the entire output ledger. Scratch stores invalidate possible overlap before establishing their singleton and joining compatible adjacent regions. Both rows2 parity cases prove their conditions and state transitions; no schedule label, coverage set or template acts as a premise.

The research artifact contains exact canonical plan/certificate bytes and row inventories. It is an experimental construction, not a hostile-input checker or production eligibility API. A separately written obligation manifest reconciles every normative obligation with concrete rows and accounting call sites. Missing premises or accounting remain explicit unresolved findings.

The cost argument covers fresh source admission/reconstruction, identities and serialization, every syntax/proof/state visit, affine arithmetic, interval arithmetic, scope handling, exact-key interning and reachable substitutions/comparisons. Charge before work; retain structural and integer bit subtotals. Decoder ingestion limits remain separately bounded and explicitly identified. Signed i32 comparisons account for `abs(-2**31).bit_length() == 32`. Source spelling variability, repeated constraints, groups, identifiers and all accepted source bytes belong in the bound. An unexplained multiplier for frontend passes is insufficient.

The envelope argument is a finite recurrence over the constructor and audited checking algorithm, with call-site operand bounds over the existing H/W/P profile. Numerical samples corroborate it; samples do not prove it. Report every fixed quota, measured instance, analytical bound and unresolved assumption separately. No tensor allocation or extent-sized proof trace is needed.

A fresh reviewer must approve complete derivations and accounting at an immutable checkpoint before the controller records C1 `proceed`. Expand the gate's artifact hash closure to include every new helper/fixture. Research code cannot activate its own gate. If a bound remains unresolved, retain `blocked`, identify the precise missing step, and revise the representation or argument. Never widen quotas or substitute a template check to make a test pass.

## Independent original-source calculator

O2 consumes exact source bytes plus an O1 verified invocation. It freshly admits those bytes, revalidates the invocation and checks all source/profile/shape identities. It evaluates the original AST, including grouping and left-to-right arithmetic, using checked i32 results at every node. It binds source declarations and axis names rather than hard-coded stencil names. A producer read evaluates that declaration at the requested coordinate; it retains no producer or output tensor.

Before equation evaluation, it acquires the entire input through O1's public traversal into an owned anonymous temporary file, checking actual length/hash and every input scalar in row-major order. Generic input chunks may split i32 values. Retain the earliest invalid index while completing preflight. On invalid input, evaluate no equations and preserve every original output scalar. This snapshot avoids a pathname open for each repeated input read. An aligned, bounded two-chunk reader accesses the private descriptor; its cache is a byte reader, not an Axiom schedule.

After valid preflight, interpret the original source declarations/bounds and stream outputs in declared Cartesian order. The permitted source family has no extra dead producer computations, and positive H/W makes all producer coordinates live. Lazy rereads preserve values and association for this narrow family; this is not an unrestricted language interpreter.

The public function is `evaluate_source_state(source_bytes, invocation, destination, *, profile, limits) -> OracleResult`. Frozen records are revalidated at entry, including nested limits. Defaults: source 65,536 bytes; retained input cache 2,097,152 bytes; AST visits 1,000,000,000; input snapshot 33,554,432 bytes; temporary payload 268,435,456 bytes; existing `ArtifactLimits` ceilings for state artifacts. Limits may only tighten. Deadlines and cancellation are cooperative; opaque O1/state validation calls cannot promise hard real-time cancellation.

Outcomes are `success`, `input_precondition_failed`, `unsupported_source`, `invalid_invocation`, `work_limit`, `cancelled`, `timeout`, `resource_limit`, `allocation_failure`, and `io_failure`. The explicit timeout/resource outcomes clarify the master's illustrative O2 list and preserve its global distinctions. Only the first two have complete state manifests. Only input-precondition failure carries a first-bad index. Failure details are bounded codes, without dumping source/input data.

State identity uses the existing state-v1 domain with C2 specialization as logical semantics. Exact source and exact-source v2 invocation identities remain separate result fields. A typed result is not a qualification receipt or trust anchor; O3 owns that later boundary.

The destination is exclusively created through safe directory operations. State is written to a private pending child, fully verified, followed by final invocation revalidation and cancellation/deadline checks, then atomically renamed to `completed`. Existing destinations remain untouched. Before publication, failure removes owned staging and closes the snapshot. After publication, cleanup cannot relabel the committed result as incomplete.

Temporary quota means **logical temporary payload**, not allocated filesystem blocks or a hard OS disk reservation. Reserve snapshot + full input/output state + maximum manifest before acquisition, without credit for deduplication. The envelope's conservative maximum is 101,711,872 bytes (97 MiB). Before acquisition or writes, O2 also checks conservative no-dedup chunk counts plus the manifest file, per-file lengths, metadata and aggregate/logical bounds against its explicit state limits. The existing state writer's final verification is too late to enforce these operational ceilings on its own. Available-space checks are advisory; ENOSPC is incomplete I/O/resource failure according to the documented mapping. Cache payload limits do not claim an RSS bound.

Counters distinguish AST node visits, preflight scalars, emitted state scalars, logical input reads and observable snapshot bytes/cache behavior. O1 and state helpers perform additional opaque verification passes. O2 must disclose them and must not label its local counters complete campaign I/O accounting.

Implementation dependencies are the model, source profile, public invocation/blob transport, state artifacts and standard library. Planner, checker, selector, emitter, native computation, optimized expression DAGs and the small reference evaluator are prohibited implementation dependencies. The existing reference evaluator is an independent comparator only in tests within its existing small envelope.

## Integration and evidence

Proof construction and O2 have disjoint implementation files and may run concurrently. Proof schema/accounting/gate changes have a single owner. Fresh independent review follows each implementation; mathematical acceptance is separate from passing tests.

After positive C1 review, reconcile the constructed schema with C3, then implement C4/C5, C6, untrusted generators and fresh checking/native integration as specified by the master plan. O3 qualification and evidence stores can proceed on the reviewed O2 boundary. Native correctness uses the single shared G3 campaign; B7 and O6 consume the same evidence. Measurement and papers remain downstream of correctness and instrument qualification.

First execute small disclosed controls and 32×32, then measure 128×128 oracle throughput before considering 2048×2048. Such oracle timings estimate test feasibility, not Axiom performance. No fresh holdout, historical primary, unqualified native speed claim or external publication is introduced by this continuation.
