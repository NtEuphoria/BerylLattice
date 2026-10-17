# Compact loop proof feasibility: C1 review record

Gate outcome: **blocked**.

First unresolved obligation: **F1 — complete, auditable hand-certificate
representation and charged-work fit under unchanged quotas**. Independent review
of `0e3c6b7d6a451cb74d6caa8666b817d3d56544d3` accepted the written general
conditional rule argument but did not approve quota feasibility. Fix round 1
does **not** resolve F1. C4–C11 remain stopped; C2/C3 retain their independent
review path. Preparatory advice is not approval.

Independent review: controller-appointed `/root/review_c1_proof_feasibility`,
2026-10-16, retained in
`.superpowers/sdd/axiom-scalability/task-C1-review.md`. The reviewer found no
unsound ledger-forgetting, scratch-frame or induction inference in the written
rules, and explicitly required complete representation/cost evidence before
proceed. No independent positive feasibility decision exists for this revision.

## Current immutable review scope

Source baseline: `958de943aeba6f8fd00dd983924499c6ca32a85c`. Its C2 source-profile
text remains byte-identical at the start of the extended design. C1 owns only
that document, the research probe, its tests and this record. There are no
production checker/planner/IR edits. The fix commit is recorded in
`.superpowers/sdd/axiom-scalability/task-C1-fix1-report.md` after committing.

| Artifact | SHA-256 |
|---|---|
| `axiom/docs/loop-plan-v2.md` | `9bf2a154db56dcb82aed11cd867cfb482a18c7cabd5775b6b92f7f905e2989d3` |
| `axiom/research/loop_proof_feasibility.py` | `89d689c9e387aac115916febb35f8f386e2c7c2f870b1e0bddd562bdd4341247` |
| `axiom/research/tests/test_loop_proof_feasibility.py` | `dd20454681ea47973a727381f761bf02af1f496474699cb858c7342f4a1e373f` |

This record is excluded from its own hash table to avoid circular identity.
Approval must bind an immutable commit and the three hashes, not a moving branch.

## Existing executable evidence

The original required RED log recorded a missing-probe failure. The initial
normal and optimized suites each passed 10 tests. Fix round 1 added an arithmetic
accounting audit; its RED log records the missing accounting function and the
outdated unresolved-obligation message. The final normal/optimized fix suites
each pass 11 tests without skips. Exact outputs are retained as
`.superpowers/sdd/axiom-scalability/task-C1-fix1-{red,green,optimized}.log`.

Measured at H=W=2048, unchanged by fix round 1:

| Outline | Primitive events | Event-trace bytes | Term nodes/depth | Integer bit work | Instrumented total work |
|---|---:|---:|---:|---:|---:|
| inline | 513 | 8,399 | 16 / 6 | 5,808 | 6,321 |
| materialize | 585 | 9,781 | 16 / 6 | 6,169 | 6,754 |
| rows2 | 693 | 11,845 | 16 / 6 | 6,377 | 7,070 |

Graph shape and structural counts remain identical at 32,128,512,2048. Integer
bit work grows; no tensor buffers or per-iteration traces are allocated. These
are measured **partial research traces**, not certificate nodes/bytes or whole
checker work. The scratch-fact hand bound is corrected to 0/3/3: materialize
needs prior completed rows, current prefix and singleton before joining.

Existing controls exercise affine endpoints; source association/dead overflow;
rectangle extension/gaps/overlaps; output reset/duplicate rejection; complete
arbitrary-q parity identities; current-row framing; stale/uninitialized/short
scratch rows; singleton dimensions and empty/single/multiple prefixes; renamed
indices/reordered definitions/transposed inline/materialize outlines; unsupported
traversals; and node/depth/work/width limits. These controls still do not
mechanically connect a complete untrusted physical certificate.

## Fix round 1: partial progress, not a resolved finding

`hand_certificate_bounds()` is a separate **analytical candidate calculation**.
It enumerates the written primitive bodies and both rows2 parity derivations:
20/13/31 primitive proof instances, 2/4/6 loop proof instances, and 22/17/22
physical syntax nodes. The appendix proposes typed payload tables, nested
base/step/exit scope/state linkage, operation coverage, value substitutions and
explicit parity replication. It accounts for source and ledger/fact bookkeeping
rather than relabeling the old traces.

Its proposed slot allocation totals 4,501 typed rows and **440,352 bytes**.
This number is **conditional on uninstantiated per-operation/per-loop rule and
payload capacities**. It is not a proven certificate-size upper bound and must
not be cited as established quota fit. The complete graph or complete expansion
proof is still absent. `expansion_completeness_established` is explicitly false.

The corresponding conservative work attempt totals **8,814,588**, exceeding the
frozen **1,000,000** limit. It includes term key/trie lookups and comparison,
interval arithmetic, affine normalization, substitutions, source visits,
coverage, states/facts, scopes and identities. It uses no general DAG Cartesian
product; nonetheless it is loose, applying worst interval multiplication to
every reserved term. Some row/algorithm capacities still need instantiation and
audit. This is neither measured complete checker work nor proof that the design
necessarily exceeds the quota. The audit tests catch omitted categories and
wrong arithmetic totals, not missing semantic premises in an unbuilt graph.

The exact remaining research task is to instantiate the scoped hand derivations
(or prove their complete expansion), derive reachable distinct
term/affine/substitution work with a charged memoization/comparison algorithm,
and obtain a complete bound at or below the unchanged quotas. Preserve all
physical operations, including dead work, complete ledger ownership, scratch
invalidation, source reconstruction, parity cases and scoped induction.
Until then F1 remains unresolved. Optional SSA storage stays unavailable, and
native correspondence/allocation/timing/publication remain separate gates.

## Gate activation mechanism

1. A controller-appointed independent reviewer examines the immutable fix commit,
   the hashes above, complete argument, logs and outstanding-obligation inventory.
2. A positive decision must explicitly establish all three schedules, output
   conservation, bounds, initialization, scalar equality and complete unchanged
   quota representation/work; otherwise retain `blocked` with the first gap.
3. The controller records reviewer identity/date, exact commit/hashes and that
   decision in a reviewed update to this file. No implementer approval, Boolean
   argument, environment variable or passing test can set `proceed`.
4. `run_feasibility()` remains a provisional blocked receipt; this reviewed
   record is the authoritative design gate. It is not production eligibility.
   Any change to approved non-review artifacts invalidates approval.

Fix-round independent re-review: pending. Approved feasibility commit: none.
