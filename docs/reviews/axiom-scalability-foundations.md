# Independent foundations integration review

Reviewer: `/root/review_scalability_foundations`. Date: 2026-10-16 UTC.

Verdict: **PASS for the reviewed foundations integration checkpoint**.
No blocking cross-module product defect remains identified. C1/F1 is still
**BLOCKED**; this verdict does not grant a positive proof-feasibility gate.
This is a review of the foundations checkpoint, not acceptance of the full
scalability plan, scalable correctness, proof feasibility or native eligibility.

## Immutable source scope

Baseline: `1011eea5edf0bd13208409e385a9b77c43adbc57`.
Integrated product checkpoint: `64da9e296f6c82f11ce5410c1421677fc6fc990f`.
Core: `0a678b4ae6d41190c4f5a8bf063caba05759d20d`, independently observed clean and unchanged.

| Component | Relevant immutable source | Component disposition |
| --- | --- | --- |
| C2 source admission | `958de943aeba6f8fd00dd983924499c6ca32a85c` | Independent specification/quality PASS |
| B1 executable boundary fixtures | `aaa6d2f2c87ff47ee15c7f4f0bc809a45846831c` | Independent specification/quality PASS; test-only |
| B2 actual tiny Core seam | `cf01790ca3fa97e22e60a842427a3c582dec5a5b` | Independent specification/ABI-quality PASS |
| C1 research feasibility | `0e3c6b7d6a451cb74d6caa8666b817d3d56544d3`, corrected by `00dd07949d6fa32437c53460cf6a340d8f85567e` | Accurate blocked follow-up accepted; F1 remains open |
| O1 bounded transport | `7e72feeed82648b059e6f9884a2ebc56cf0a27a0`, corrected by `64da9e296f6c82f11ce5410c1421677fc6fc990f` | Independent fix1 specification/quality PASS |
| B3 owned lifecycle and B2 retrofit | `9912ead6c330fb0f302e687aca577fecad005bc0` | Independent specification/ABI-quality/ownership PASS |

I read the exact component changes and their cross-module dependencies, briefs,
reports and independent reviews, the progress ledger, shared design/plan and
controller implementation-record draft. I independently matched the retained
C2/B1/B2/B3/O1-fix1 diffs to their exact Git ranges and checked whitespace for
the full baseline-to-checkpoint diff. No existing baseline path is modified:
all 37 changed paths are additions. Thus existing v1 code, canonical formats,
CLI defaults and native-unavailable implementation remain byte-identical.
This does not substitute for integration tests of the added modules.

## Cross-module assessment

**Source and identity boundaries are consistent.** C2 freshly parses exact
source bytes, retains the original AST, and separates exact source, normalized
family, fixed specialization and source-policy identities. O1 reuses this sole
admission API, re-admits retained source, checks H/W and exact extents before
opening buffer streams, and binds exact source and original buffer bytes in
its invocation identity. Transport retains out-of-range signed-i32 values for
real source preflight rather than treating them as transport rejection.
State-v1 mapping is an explicitly separate hash domain; it neither widens v1
admission nor proves a correspondence receipt. O1 imports no research code.

**Native authority is not inferred from metadata.** O1's host-contract string
is a requirement, not evidence of live disjoint allocations. B3 constructs
separate owned input/output and operation scratch allocations, checks private
handles and fixed dimensions, and invokes the actual generated typedef through
the B2 binding. Its opaque uint64 specialization token is expressly not a
source/build digest or proof of source admission. Full source/check/build
revalidation remains the future B5/B6 boundary. Neither the public transport
records nor the private B2 binding helper are promoted to a standalone
production execution authority.

**Ordering, resource meanings and ownership agree.** The B1 test-only adapter
specifies source rejection before scratch/body. B3 implements preflight before
operation allocation, full scratch initialization, private checked invocation,
descriptor checks and cleanup through retained owners. Its preparation-byte
limit bounds input/output/scratch requested bytes; it is not the source plan
workspace cap or proof of plan resource feasibility. Abstract plan capacity,
requested allocator bytes, bookkeeping, allocator slack and RSS remain separate.
B3's registry is private synchronous trusted state, not an arbitrary-pointer,
concurrent-owner or hostile same-process validation API. Full acquisition and
independent comparison remain necessary before any semantic acceptance.

**The native evidence is real but deliberately tiny.** The B2 fixture uses
actual pinned Core emit-c output without generated-C rewriting or C substitute
stencil computation. The B3 retrofit routes it through the shared lifecycle.
B1 callbacks, large dimension arithmetic and research traces are not presented
as native execution. B2 runs use C -O0; B3 native controls use C -O1; Python -O
checks Python guards and is not native optimization qualification. B3's direct
linked-allocation interposition controls explicitly miss mmap, shared-library
internals and other unqualified paths. Complete allocation accounting and the
future emitted-kernel campaign remain blocked, regardless of balanced counters.

**Public-record revalidation remains an explicit consumer obligation.** O1's
fix closes float/bool equality and mutable-source bypasses with exact field and
container validation before fresh file acquisition. Consumers still must call
revalidate at their trust boundary and consume complete traversals; scalar
cache fingerprints are not an OS snapshot against a same-UID concurrent writer.
Per-blob limits and bounded buffers do not replace enclosing-store aggregate
budgets or read/acquisition accounting. These limitations are stated consistently.

**C1 has no positive gate.** The accepted general conditional argument and
11 accounting controls do not instantiate complete certificates. The proposed
440,352 bytes depend on unproved capacities; the 8,814,588-unit conservative
work estimate exceeds 1,000,000 but is not an impossibility lower bound. F1
requires complete hand graphs or a proven complete expansion and fully charged
work within unchanged quotas. C4–C11 remain stopped. The later 32×32 native
oracle comparison, 2048×2048 execution, timing and publication gates are absent
and explicitly future work, not omissions from a claimed completed milestone.

## Findings and dispositions

No concrete cross-module product defect has been identified in this scoped
review. Final B3 and O1 independent verdicts and the immutable ordinary-product
receipt are now present and accepted for their stated scopes. O1-R1 (typed-record revalidation) and O1-R2 (ordinary test discovery)
are resolved by the independently accepted fix1. C1-F1 remains an intentional
blocking research obligation, not a resolved finding or foundation acceptance.

Documentation consistency item: the tracked C1 review record still ended with
“Fix-round independent re-review: pending” when first inspected, although the
exact fix1 rereview accepted accurate blocked reporting. I requested a
controller-owned correction that preserves “Approved feasibility commit: none.”
The controller corrected that paragraph, naming the exact review commit and
acceptance scope while retaining F1 open and no approved feasibility commit.
I inspected the correction and independently matched all three C1 non-review
artifacts to the exact reviewed commit: this item is resolved.

## Verification receipts

- C2: retained 33 focused/frontend/reference and 21 optimized-Python checks;
  additional admission-only overlap probe covers 955 v1 shapes across three
  policy settings (2,865 cases), not execution.
- B1: 14 normal and 14 Python-O checks plus three intentionally failing bad
  adapters. These are test-only contract evidence.
- B2: 13 native normal and 13 Python-O checks plus 50 regressions. Original
  component review independently checked complete tiny valid/rejected states,
  exact generated output and ABI failure controls.
- B3: retained 18 normal and 18 Python-O checks, including actual ordinary,
  sanitizer/interposition/fault controls and the B2 lifecycle retrofit. Independent specification/ABI-quality/ownership review passed. Its
  report-precision finding is resolved: all 220 lifecycle calls and five
  integrity controls acquire/compare complete state; individual metadata-boundary
  controls do not each reacquire. No product change was required.
- O1 fix1: retained 14 normal and 14 Python-O checks plus 28 frontend/state
  regressions in each mode; ordinary focused discovery uses PYTHONPATH=src.
- Full research suite: immutable `7e72feeed82648b059e6f9884a2ebc56cf0a27a0`,
  97 tests in 122.864s, exit 0; receipt wall time 123.04336452484131s.
  `integration-research-receipt.json` binds source archive SHA-256
  `9d59a6d61f09850b9f16ebb09c28bd64e1aef702cc5b1378c39afce693b966e0`
  and log SHA-256
  `dedc6acc4a6a90b992f425aa5d89a3fe6079f86a5b8adadec2f9d0b5adf32d10`.
  I independently matched the retained log hash and final count. Research
  Python implementation/tests and source admission have no changes between
  that archive and the integrated checkpoint. This is regression evidence,
  not C1 feasibility approval.
- Full standard product suite: immutable `64da9e296f6c82f11ce5410c1421677fc6fc990f`
  at `/workspace/scratch/axiom-foundations-product-pl7g5502`: **239 tests in
  356.639s, OK (skipped=12), exit 0**, with PYTHONPATH=src and native selectors
  unset. Receipt wall time is 356.8975076675415s. Its source archive SHA-256 is
  `4e8a538979133ff6a8b7f1465edb5b32fcc41f0e3ef259ce79817ac3b1b7014b`;
  log SHA-256 is
  `7b74bbd5f6f7dbad7cca1bceb2b11952dcf1d6e36906708b187b0eb7f3178b49`.
  I independently verified the log hash and final result, and byte-compared all
  113 tracked files in the test archive against this exact Git checkpoint:
  every file matches. The 12 skipped native cases are not passes; actual native
  qualification remains the separate selected-tool B2/B3 campaigns above.
  The earlier broad run's two corrected errors remain honestly recorded and
  are superseded for ordinary integration discovery by this immutable run.

I did not rerun passing component/full suites, invoke native builds, edit product
or shared documentation, create commits/worktrees, spawn agents or publish/contact
external parties. This report is the only artifact I wrote. The controller owns
the final documentation commit and new recovery archive. Existing local recovery
checks do not establish independent cloud-task restoration; no final bundle or
new-cloud recovery claim is made by this review.
