# Loop plan v2: source profile and admission

This section specifies explicit scalable source admission only. Loop proof
feasibility is unestablished. Source admission does not establish plan
correctness, abstract storage bounds, native allocation, timing, or publication
eligibility; those are separate gates.

## Public source boundary

```python
admit_source_v2(source_bytes: bytes, *, profile: SourceProfileV2,
                limits: SourceLimitsV2) -> AdmittedLoopKernel
```

These records and the function live in `axiom.source_profiles`. Both keyword
arguments are required. Use `SourceProfileV2()` and `SourceLimitsV2()` to select
the supported configuration explicitly. V1 `parse_source` / `admit_source`, its
256-input-cell bound, canonical bytes, and hashes retain their existing behavior.

`SourceProfileV2` is immutable, with `version=2`,
`profile_id="axiom-stencil-fixed-buffer-v1"`, `max_height=8192`,
`max_width=8192`, `max_input_cells=2**23`, and
`index_semantics="checked-i32-row-major"`. Only these exact profile values are
supported; altered profile versions or semantics are rejected. Dimensions
follow the first and second shape declarations, independently of their names.

`SourceLimitsV2` is immutable, with `version=2`, `source_bytes=65536`, and
`expression_nodes=100000`. Quotas may be reduced to positive exact integers, but
cannot exceed these defaults. The existing parser also retains its ten-digit
integer-token and 32-level expression bounds. Boolean values do not qualify as
integers. Unknown versions and mutable configuration values are rejected with
`ValueError`. Source diagnostics use the existing `DiagnosticError` and byte
spans. Mutable source buffers and caller-created ASTs are not admitted.

## Supported fixed-buffer source semantics

```text
1 <= H,W <= 8192
P = (H+1)*(W+1) <= 2^23
O = H*W
input: i32[P], admitted values 0..1023
producer(r,c) = (input(r,c)+1) * (input(r,c)+1)
output(r,c) = ((producer(r,c)+producer(r,c+1))
                +producer(r+1,c))+producer(r+1,c+1)
```

H/W are fixed source parameters; values and host-owned buffers are runtime data.
The original parsed scalar tree governs computation. Admission compares the
exact supported normalized binary tree, ignoring parenthesis wrappers but not
association. Renaming bound symbols preserves semantics, including axes whose
names shadow tensor names. Changed grouping, ranges, tensor roles, or scalar
operations cannot be admitted as this canonical family. Structural validation
runs before profile recognition.

Every scalar node, including dead operations, uses checked i32 semantics.
Producer values are `1..1,048,576`; successive output sums are bounded by
`2,097,152`, `3,145,728`, and `4,194,304`. Mathematical index reasoning must
separately establish that generated i32 arithmetic and checked host byte
arithmetic fit their machine domains. These engineering dimension/cell limits
are neither a language theorem nor a native memory promise.

The source boundary semantics require row-major input preflight. Failure
identifies the first invalid input index and preserves the complete input and
original output. No scratch allocation, initialization, or body execution may
precede that decision. Success and input-precondition failure are the only
completed semantic states; invalid handles, native resource failure, traps,
timeout, cancellation, and missing acquisition need separate execution-failure
records. C2 binds these semantics in identity; it implements no execution path.

The execution profile additionally requires `0 <= scratch_capacity_cells <= P`,
including unused capacity and hand-authored plans. One complete semantic state
is strictly below 64 MiB, and reserved plan scratch is at most 32 MiB. These
execution requirements and actual memory/work/evidence budgets remain for the
later plan and execution gates.

## Retention and identities

`AdmittedLoopKernel` retains `source_bytes`, `source_digest`, the original
`source_module` AST, `height`, `width`, `input_interval`, original
`source_constraints`, their intersected workspace `cap`, `objective`, the
selected `profile`, and `version=2`. `input_cells` and `output_cells` are derived
properties. Its constructor uses the same fresh-byte admission boundary, so a
caller cannot construct an admission result by supplying asserted AST fields.
All retained structures are immutable parser-derived records.

Three distinct hashes serve distinct purposes:

* `source_digest` hashes the exact retained bytes, including names, spelling,
  comments, and formatting. The shared boundary name `source_sha256` is a
  read-only derived property.
* `family_digest` hashes canonical UTF-8 JSON with identity version
  `axiom-loop-family-v2`, the source-profile version/envelope/index semantics,
  alpha-normalized tensor types, roles, equations, input range, checked scalar
  arithmetic, and preflight boundary semantics. It excludes literal H/W and
  optimization preferences. Only the recognized canonical profile is hashed as
  this family. `family_semantics_sha256` is a derived property.
* `specialization_digest` hashes identity version
  `axiom-loop-specialization-v2`, the family hash, exact H/W, and the contract
  that dimensions are fixed while inputs and host buffers are runtime data.
  `specialization_semantics_sha256` is a derived property. A future proof must
  bind this specialization.

Canonical JSON uses sorted keys, compact separators, UTF-8, and no NaN values.
The v2 version domains differ from v1 semantic identities. Shape changes preserve
the family hash and change the specialization hash; spelling changes affect the
source hash alone. Shared boundary aliases are never separately mutable hashes.

Source constraints and objectives have separate versioned canonical identities:
`constraint_digest` binds `axiom-loop-source-constraints-v2` and the effective
source `plan_workspace_bytes` cap; `objective_digest` binds
`axiom-loop-source-objective-v2` and the parsed objective. Repeated source caps
intersect to their minimum. The original constraint declarations are retained;
their ordering/spelling remains bound by the exact source hash. Unknown source
properties/objectives and caps outside exact integer `0..2^31-1` are rejected.
Changing source caps or objective preserves the value-semantic hashes. Future
checking/replay must bind policy identities and independently intersect each
additional requested property with fresh source constraints.

Source ordering/path fingerprints, generated C, binaries, compiler pins, plans,
certificates, and execution instances require their own identities. None can
substitute for source, family, specialization, constraint, or objective identity.

## C1 research gate and scope

C1 specifies a restricted proof system and supplies hand derivations plus bounded
experiments in `research/loop_proof_feasibility.py`. It does **not** implement a
physical IR decoder, production certificate checker or planner. Its
`run_feasibility() -> FeasibilityReceipt` returns `blocked` until a separate
independent review approves the finished artifact identity. Independent review
found F1: complete hand-certificate quota fit is unestablished. In this revision it
always returns `blocked`; there is no argument, environment variable or test
success bit that changes it. The reviewed gate record belongs in
`docs/reviews/loop-proof-feasibility.md`. A controller may activate the *design*
gate there after reviewing an immutable commit and the exact three non-review
artifact hashes. That record does not create production eligibility. Further
changes to those artifacts invalidate approval and require another review.

The executable receipt's `complete` fields mean the bounded experiments finished.
They do not mean the written induction theorem was mechanically checked. A
positive test cannot set the reviewed gate to `proceed`. C4–C11 must remain
stopped while the reviewed gate is blocked; independently reviewed C2/C3 may
continue. Native compiler correspondence, acquisition/comparison, allocation,
timing and publication remain separate gates. Keep this work private.

## Operational machine and body theorem

A source specialization fixes H/W with `1 <= H,W <= 8192` and
`P=(H+1)(W+1) <= 2^23`. Data and caller-owned buffers remain runtime inputs. The
physical syntax is ordered blocks of `const`, `input_load`, `scratch_load`,
`add`, `mul`, `scratch_store`, `output_store` and `for`. Every scalar result is
an i32; each executed add/multiply must fit i32, including dead work. For loops
have literal specialized nonnegative i32 `L <= U`, positive unit step, and
representable terminal counter U. Empty loops execute no body. Each iteration
has fresh lexical SSA; a nested block may read outer scalar bindings, but local
bindings cannot escape. No scalar SSA is loop-carried. Retention uses declared
scratch. No data-dependent branches, calls, pointers, implicit buffers, output
loads or input stores exist.

Indices contain only affine combinations of lexical index binders and literal
constants, optionally literal modulo two of an affine expression. They cannot
read scalar SSA or tensor data. Source shapes are specialized before analysis.
Input/output accesses have two mathematical coordinates. Scratch addresses are
`pitch*physical_row+column`, with explicit pitch and reserved capacity. Every
reserved cell counts. Capacity outside `0..P` is unsupported admission and
semantic unknown (`UNSUPPORTED_PLAN_CAPACITY`), never a source-constraint
counterexample. Initial scratch is logically uninitialized regardless of native
zeroing. Origin tuples identify retained AST-node byte offsets; they do not prove
correctness and cannot point to arbitrary UTF-8 interior bytes.

Conditional body theorem: given an admitted exact source and specialization, a
well-formed physical plan, stable pairwise-disjoint correctly sized buffers,
input values in `0..1023`, mathematical index semantics, checked-i32 scalar
transitions, and correct implementation of the rules below, an accepted complete
certificate entails finite termination, all access bounds, initialized scratch
reads, unchanged input, no hidden effects, exactly one write per output cell,
and exact source-equation values. It entails only metrics separately derived by
the specified complete metric pass. Optional SSA storage is not yet part of this
theorem. The theorem is a written conditional argument; neither these tests nor
review make it machine-checked formal verification. The Python checker remains
trusted software. This theorem does not verify Core/C compilation or native
address evaluation; corresponding native experiments are separate evidence.

## Judgment, ownership and proof rules

Write `Γ; (V,S,L) |- block => (V',S',L')`. Γ contains typed lexical binders,
affine premises, and scoped induction parameters. V maps scalar SSA identifiers
to exact term-DAG nodes and proved i32 intervals. S contains universally
quantified initialized/value facts with rectangular domain, physical map and
source-derived expression. L is the **entire** output ledger: a disjoint union
of physical cells with exact established source values. L is owned state, not
a proposition subject to weakening. Immutable input and layout/capacity facts
are established structurally. The judgment has no implicit effects.

1. **Source and scalar rules.** Reconstruct `Input(a,b)`, integer constants,
   ordered `Add(x,y)` and `Mul(x,y)` from actual operations. Every operation has
   its own checked-i32 interval proof; a dead result does not erase its operation.
   Expand producer references from the retained AST using capture-avoiding
   substitution of its bound indices. Equality is ordered structural DAG
   equality after affine index normalization. Neither reassociation nor
   commutativity of scalar operations is an equality rule.
2. **Bounds and reads.** An input read requires both coordinate inequalities. A
   scratch read additionally requires membership in an existing initialized
   rectangle through its *physical* map and matching source-value substitution.
   A logical-row label alone proves neither physical membership nor a value.
3. **Scratch store.** Prove address bounds and the scalar value. Remove every S
   fact whose physical footprint might overlap the write. Preserve only checked
   disjoint frames. Splitting a fact first may preserve unaffected pieces; simply
   forgetting the entire old fact is safe. Add the new singleton. Initialization
   without a matching value does not establish a producer fact.
4. **Rectangle rules.** Half-open empty rectangles denote the empty set. Check
   endpoint order. Split at a checked interior endpoint, or join exactly adjacent
   pieces with equal other endpoints, compatible physical maps and pointwise
   identical value substitutions. A gap or overlap is rejected. Prefix plus next
   singleton gives prefix extension. Row-major injectivity follows from
   `pitch*(a-a') = b'-b` with `|b'-b| < pitch`: the only multiple of positive pitch
   in that interval is zero, so `a=a'` and `b=b'`. This applies to physical rows;
   the map `logical_row mod 2` is not injective over all logical rows.
5. **Output store.** Require a valid coordinate, exact source output term and
   disjointness from every current L piece. Append exactly the singleton. A
   same-value duplicate is still rejected. Split/join may change L's
   representation only by exact disjoint-union equality, including values and
   multiplicity. There is no ledger-forget rule. A loop invariant that drops an
   incoming output write cannot satisfy the loop rule.
6. **Sequence.** Feed the entire result state to the next operation. A production
   derivation must cover each physical syntax node exactly once, with nested
   body syntax checked once symbolically. No certificate omission can erase a
   store or dead operation. Pure lemmas may be shared; state transitions cannot
   fork or duplicate owned output history.
7. **Loop induction.** For `for k in [L,U)`, check base `incoming => I(L)`, using
   exact equality for the incoming ledger and conservative weakening only for
   scratch. Introduce fresh arbitrary k and a scoped parameter for `I(k)` under
   `L <= k < U`. Check the actual body to a state that establishes `I(k+1)` with
   exact ledger equality. Discharge that scoped parameter and conclude `I(U)`.
   The base and step include all incoming framed output writes. If L=U, return
   the actual incoming state; do not execute an unreachable body symbolically
   as though its reads had occurred. If a generic certificate checks that body
   under contradiction, no conclusions may escape that scope. Substitution uses
   binder identities, not textual names; source, plan and region binders have
   distinct namespaces. Inner scalar bindings and induction hypotheses cannot
   appear in an outer postcondition.
8. **Proof DAG.** Dependencies point only backward. An induction hypothesis is
   a locally bound premise discharged by rule 7, not a cyclic proof reference
   or an unrestricted node asserting its own result. Reject forward/cyclic
   references, missing bases, wrong successor substitutions, escaped hypotheses
   and capture. Each premise and actual state transition must be checked.

Soundness argument by derivation structure: scalar rules preserve exact values
and bounds under their checked intervals. Reads consume initialized facts;
stores replace precisely the potentially affected facts while disjoint frames
remain true. Rectangle rules preserve denotation. Output stores extend the
exact ledger with a disjoint singleton; hence multiplicity remains one.
Sequence composes these invariants. For a loop, ordinary induction on the
finite natural number `k-L` establishes I(k) at every actual entry. The checked
base establishes zero; the arbitrary-k body rule establishes the successor.
At U the ledger is exactly the invariant's exit ledger. No syntactic certificate
can use induction without those premises. Loop termination follows from the
finite literal trip count and recursively terminating bodies. Structural syntax
excludes input writes and hidden effects. Final ledger equality with the output
rectangle proves totality and uniqueness, and its values prove source equality.
This is a general argument for every admitted input and index, not induction
inferred from successful sample executions.

## Bounded affine and parity reasoning

For a box domain, bound `a0 + Σ ai*xi` by selecting the lower endpoint for a
positive coefficient and upper endpoint for a negative coefficient; reverse
choices for the upper bound. Each substitution preserves an inequality because
multiplication by a negative coefficient reverses its direction. Eliminate
innermost variables first for dependent proof-prefix endpoints, permitting only
endpoints affine in earlier binders. Physical loop bounds remain constants. The
probe implements independent-box elimination; dependent endpoints and arbitrary
affine implications are not executable probe features. Unsupported goals stay
unknown. No unrestricted SMT success token is a rule.

For rows2, mathematical Euclidean division supplies unique `r=2q+p` with
`p in {0,1}` for every nonnegative integer r. The finite cases are:

| p | current slot | r+1 decomposition | next slot |
|---|---|---|---|
| 0 | 0 | 2q+1 | 1 |
| 1 | 1 | 2(q+1)+0 | 0 |

These are identities in arbitrary q, checked as affine expressions by the
probe. They do not evaluate just rows zero and one. Both arguments r and r+1
are nonnegative, so direct native remainder has the required mathematical
meaning. Distinct slots give disjoint intervals `[slot*pitch,(slot+1)*pitch)`
for positive pitch; column membership preserves disjointness. The partition is
complete even for H=1. A production proof may discharge an unreachable case by
a checked contradiction, but cannot omit it on a generator assertion.

## Three hand-derived certificates

Let `T(a,b)` abbreviate the *expanded retained AST*
`Mul(Add(Input(a,b),1),Add(Input(a,b),1))` and let
`E(r,c)=Add(Add(Add(T(r,c),T(r,c+1)),T(r+1,c)),T(r+1,c+1))`.
These abbreviations are not accepted certificate axioms. The intervals are
`Input in [0,1023]`, each producer add in `[1,1024]`, T in `[1,1048576]`,
and successive output sums in `[2,2097152]`, `[3,3145728]`, `[4,4194304]`.
All are i32 safe independently of the actual input values.

**Inline.** Capacity zero, S empty. Outer invariant at row r is exact ledger
`[0,r)×[0,W)`. Its inner invariant at column c is that ledger disjointly joined
with `[r,r+1)×[0,c)`. The base c=0 contributes an empty rectangle. For arbitrary
`0<=r<H, 0<=c<W`, all four input coordinates are in
`[0,H+1)×[0,W+1)`. Actual scalar operations establish the four T terms and E in
its original association. The singleton `(r,c)` is disjoint from both ledger
pieces, so the output store and adjacent join extend the column prefix. At
c=W, joining the full row with prior rows yields `[0,r+1)×[0,W)`, exactly the
outer successor. Base r=0 is empty; exit r=H is the entire output. Reordering
independent definitions or alpha-renaming leaves these rules applicable. A
column-major traversal exchanges the two prefix axes, with the same proof;
no schedule tag appears in any trusted inference.

**Materialize.** Pitch W+1 and capacity P. Producer outer invariant at row a
is initialized/value rectangle `[0,a)×[0,W+1)` with value T. Inner invariant
adds `[a,a+1)×[0,b)`. At arbitrary `0<=a<H+1, 0<=b<W+1`, input bounds and T's
arithmetic are proved; row-major injectivity frames earlier writes while a
scratch store establishes the next singleton. Prefix joins establish the inner
and outer successors. Initial S is empty; final S is the entire producer
rectangle. No output write occurs in this phase, so its *exact* ledger remains
its incoming ledger (empty here). The subsequent consumer uses the inline
ledger proof and four initialized scratch reads from that complete rectangle.
The consumer preserves S; sequence connects the real producer exit to consumer
entry. Column-major consumer traversal is also admissible by swapping the
prefix decomposition. No materialization label provides initialization.

**Rows2.** Pitch W+1, capacity `2(W+1) <= P` because H>=1. Stage logical row zero
into physical slot zero with the producer column-prefix proof, before the outer
loop. At entry r, I(r) consists of exact output ledger `[0,r)×[0,W)`, complete
current-row fact `S[(r mod 2)*pitch+b]=T(r,b)` for `0<=b<W+1`, and immutable
input. Other scratch facts may be discarded.

At arbitrary `0<=r<H`, stage logical row r+1 into slot `(r+1) mod 2`. The stage
inner invariant at j contains the unchanged complete current row and the next
row prefix `[0,j)` with value T(r+1,b). Its base j=0 is empty. For arbitrary
`0<=j<W+1`, input coordinate `(r+1,j)` is valid. Each store invalidates any old
target-slot fact. Both parity cases prove disjointness from the current slot;
column injectivity preserves the next prefix. Store plus join gives `[0,j+1)`.
No output store occurs, so the outer ledger is conserved exactly throughout
staging. At j=W+1 both complete rows exist.

The consumer invariant at c contains both rows and exact ledger
`[0,r)×[0,W) ⊎ [r,r+1)×[0,c)`. Scratch reads instantiate the current/next facts
at c and c+1; `c+1<=W` is inside their half-open upper bound W+1. The exact E
term and output singleton extend the prefix. At c=W, join the completed row
into `[0,r+1)×[0,W)`. Forget the old current row, retain the newly staged row;
substitution r:=r+1 makes it precisely I(r+1). Base I(0) follows from explicit
stage-zero and empty output; exit I(H) gives complete output. H=1 uses one
refill and one consume pass; W=1 stages two columns and consumes one. Neither
needs a special branch. These base/step/exit arguments quantify over every
admitted dimension, independently of the probe's selected dimensions.

## Resource and result boundaries

`plan_workspace_bytes = 4*reserved_scratch_cells`, including unused capacity.
This excludes retained SSA and native memory. For the hand outlines with one
input load, one constant, one shared add and one multiply per producer, dynamic
primitive counts (excluding loop-control nodes) are `20*H*W` for inline,
`5*P+8*H*W` for materialize and rows2. These formulas describe these written
outlines only; a production metric pass must derive counts from actual syntax,
including dead work, using sums and trip-count multiplication. It cannot infer
metrics from a schedule label. Empty loops multiply by zero. Exact metrics
must fit 256 bits; a failed partial pass supplies no exact whole-plan result.

`abstract_storage_bytes-v2 = 4*(reserved scratch + peak live transient i32 SSA)`
is **deferred/unavailable** until separate compositional liveness rules are
reviewed. Result allocation precedes last-use retirement; dead results retire
immediately afterward. Empty/single/multiple loops need explicit summaries;
a zero-arena SSA-staged plan must not be reported as zero retained storage.
Native requested heap bytes, lifetimes, cleanup retention and allocation counts
require actual instrumentation; RSS, caller buffers, overhead and stack/spills
are separate quantities. None substitutes for the arena metric.

Production `LoopCheckResult` must distinguish semantic valid/invalid/unknown,
constraint status, certificate verified/rejected/unsupported/incomplete,
completion, failure phase/reason, optional checked witness, completed metrics,
work and all versioned source/plan/certificate/constraint identities. Missing
or failed proof is unknown unless there is a concrete validated semantic witness
or demonstrably invalid structural effect. Artifact decoding errors are typed
artifact rejections. Exhaustion is incomplete unknown. Eligibility requires
verified proof, valid semantics, satisfied constraints and complete checking.
The research receipt has no eligibility field and is not this result type.

## Quotas, measurement and implementation obligations

Initial limits remain unchanged: source 65,536 bytes; plan 262,144 bytes;
certificate 524,288 bytes; IR nodes/scalar definitions 4,096 each; loop nesting
4; affine terms 16; active facts 256; region pieces 1,024; proof nodes 16,384;
parity cases 16; symbolic nodes 65,536; symbolic depth 256; intermediate integers
256 bits; deterministic work 1,000,000. `LoopLimits.symbolic_nodes` and
`symbolic_depth` will own the production DAG limits. V2 integer ingestion must
limit tokens to 78 decimal digits before conversion, then check field bounds;
its serializer independently enforces the bounds. V1's ten-digit serializer and
quotas stay unchanged. A quota change needs explicit version/rationale and review.

The probe records primitive check events, encoded event-trace bytes, interned
term nodes/depth and charged work. Its `primitive_events` is the number of primitive
check events, **not** a measured production certificate DAG size. Its
`trace_bytes` is event-trace JSON, **not** a production certificate encoding.
The `outline_scratch_fact_bound` and `outline_region_piece_bound` fields are
conservative hand-outline bounds,
not instrumented production peaks. All four distinctions are intentional:
production encoding/complete decoder accounting is C3–C5 work and cannot be
claimed measured by this research code. The three written outlines require at
most three simultaneous scratch facts, three output pieces before joining,
four nested lexical scopes and two parity cases. Review must assess whether
lowering the explicit obligations fits the unchanged quotas; this revision
cannot freeze quotas on the basis of trace byte counts alone.

`research-bitwork-v1` charges one structural visit per recorded primitive check
plus integer bit work: add/compare cost `max(1,bitlen(a),bitlen(b))`, multiply
cost `max(1,bitlen(a))*max(1,bitlen(b))`. Charges precede those arithmetic
operations; widths are checked before accepting results. Structural visits and
bit work are separate. Python helper construction, source admission, affine
operator assembly, term-key hashing and the constant parity table arithmetic
are not exhaustively charged here. The receipt's work is the **instrumented
probe work**, not a complete production checker cost. Full charged normalization,
source/IR/premise visits, substitution/comparison, bounded integer operations,
byte/item/token ingestion, deadlines and memory limits remain mandatory.

Term interning keys contain child IDs, never expanded trees. The probe checks
arity, backward references, depth and node quota before appending a new node.
It expands only the bounded retained source AST, not arbitrary shared DAGs.
A production comparison/substitution algorithm must memoize `(node,substitution)`
and visited node pairs; charge before each work item and enforce width/depth
before constructing new nodes. Interning is not a premise that discharges an
operation obligation. The shared-expression control builds 32 doublings with
linear nodes, not an exponential tree; it does not prove that a future generic
substitution implementation obeys those requirements.

No probe loop iterates over H, W, P or output cells: loops traverse the fixed
four producer coordinates, two parity cases, bounded term/AST structures,
rectangle pieces, affine coefficients or three outlines. Graph-shape equality
at 32,128,512,2048 is a regression control for that fact, not the proof of it.
Integer bit work changes with dimension; flat structural counts imply no flat
wall-time claim. Input/output tensors are never allocated by the probe.

## Complete obligation inventory and design alternatives

| Obligation | Research evidence | Production obligation still required |
|---|---|---|
| Source specialization and exact AST | C2 admission; `source_term` rebuilds AST | Bind exact plan/source/certificate identities and valid AST origins |
| Scalar equality and overflow | Original association, reordered definitions, dead overflow controls | Visit every physical definition, including dead/omitted operations |
| Bounds | Arbitrary-index box endpoint checks; written dependent-prefix rule | Complete charged affine/substitution implementation |
| Initialization and overwrite | Both slots, prefix extension, stale/uninitialized/short-row controls | Generic mapped facts, matching values and store invalidation |
| Output conservation | `Ledger` rejects reset/duplicate; prefix gap/overlap controls | Entire physical block coverage, no hidden staging output write |
| Induction | General base/step/exit argument; zero/single/multiple prefix checks | Scoped hypothesis decoder, base provenance, capture-free substitution |
| Parity and layout | Complete arbitrary-q identities, both disjoint slots; injectivity proof | General checked layout/footprint premises and mod-argument bounds |
| Alternate structure | Alpha-renamed indices, independent definition order, transposed prefixes | Hand-authored physical plans/certificates at C3–C5 boundary |
| Proof resource bounds | Trace/DAG/work measurements and hand bounds | Actual encoded proof counts, full work enforcement/hostile decoding |
| Metrics | Outline formulas and storage exclusions | Exact syntax metrics; optional liveness separately reviewed |

Missing/escaped induction hypotheses, hidden output stores, omitted physical
operations, source-origin forgeries, general value-incompatible joins, arbitrary
binder collisions across proof namespaces and cyclic *certificate* references
are **not implemented negative controls** in this probe, because their physical
IR/proof decoder does not exist yet. They remain explicit required controls for
C3–C5. Term-DAG forward references and local binder collisions are checked here.
Unsupported rows2 column-major traversal and unknown outline names fail closed.
No unsupported control is reported as passed.

A restricted validator is sufficient at the rule-design level if independent
review accepts the stateful induction rule and these hand derivations. Its
remaining difficulty is correct state ownership/substitution and full syntax
coverage, not discovering a formula for row parity. Solver certificates could
extend affine implication coverage only with independently checked proof objects;
a solver success bit would add an unacceptable premise. A general polyhedral
engine offers more region representations but does not itself prove scalar
association, scratch initialization, overwrite invalidation, ledger conservation
or scoped induction. Neither alternative repairs a missing state rule. If the
review finds a missing rule, record the first obligation and keep C4–C11 blocked;
do not replace the proof with planner templates or iteration enumeration.

The executable `Ledger` checks rectangle geometry only; source-term equality is
probed separately. `check_prefix` constructs a hypothetical arbitrary-index
step and instantiates its documented exit; it does not parse or independently
validate an untrusted invariant. The materialize scratch proof and the linkage
of nested induction states are hand derivations above. Schedule names choose
which *research experiment* to run, never a production acceptance rule.

## C1 F1 follow-up: encoding proposal and remaining work blocker

The independent review of `0e3c6b7` accepted the written conditional rule
argument and blocked quota feasibility. F1 is **not resolved** by the following
analysis. It supplies an auditable encoding/counting proposal and a conservative
work model, not a completed proof artifact or production checker. Its work bound
is 8,814,588, exceeding the unchanged 1,000,000 quota. Therefore there is still
no justification for `proceed`. This upper bound does not prove that the three
certificates intrinsically require that much work; a tighter constructive
sharing/accounting derivation may succeed. No quota is changed.

`hand_certificate_bounds()` audits the arithmetic of this proposal separately
from the existing measured event traces. Tests reject omitted tables, omitted
work categories and incorrect claimed totals. Those tests do not prove the
proposed row-capacity assumptions or validate a certificate. That distinction is
essential: the proposal must be instantiated or its remaining expansion claims
independently justified before it can resolve F1.

### Physical inventory and parity replication

Use the exact written plans above, with a producer primitive body
`input_load, const, add, mul, scratch_store`; a consumer body
`4*scratch_load, 3*add, output_store`; and an inline consumer body
`4*(input_load,const,add,mul), 3*add, output_store`. Explicit physical loops
surround these bodies. Ordinary loop bodies have one arbitrary-index derivation;
only the rows2 outer body is replicated into two parity subderivations. Stage
zero appears once, followed by both refill/consume cases. Thus:

| Quantity | Inline | Materialize | Rows2 |
|---|---:|---:|---:|
| Physical nodes including loops | 22 | 17 | 22 |
| Physical scalar definitions | 19 | 11 | 15 |
| Primitive proof instances N | 20 | 13 | 31 |
| Induction proof instances K | 2 | 4 | 6 |
| Store proof instances S | 1 | 2 | 5 |

For rows2, N is `5 + 2*(5+8)` and K is `1+1+2*(1+1)`: stage-zero loop,
outer induction, and stage/consumer loops in both cases. The single outer body
syntax is bound to both case derivations; this is not duplicate physical code.
The proof graph must explicitly attach operation IDs, source origins and lexical
scopes. A union of coverage sets must equal each actual block's ordered list.
Disjoint case derivations may cover the same body under different exhaustive
parity hypotheses; a missing case or missing operation is an error.

### Proposed encoding and reservation calculation

The proposed research encoding is canonical compact JSON arrays with integer
opcodes and typed table indices. Source, plan and specialization hashes, versions,
profile/constraint identity and the table directory live in a header. No opaque
schedule token supplies a premise. Every table index is typed; every dependency
points backward or to a locally bound induction assumption discharged by its
owner. Scope entries distinguish source, physical and quantified region binders.
Source origins reference actual retained AST nodes, checked against source bytes.

A proof row contains rule opcode, scope, physical operation, input/output state,
typed payload/substitution references and at most eight premise references.
Bigger conjunctions use explicitly counted conjunction rows. A term row contains
opcode, scalar children or input coordinates, scope and checked interval. An
affine row contains a constant and at most two `(binder,coefficient)` pairs in
these particular outlines, plus a separately typed literal-mod2 argument where
needed. A region row contains four half-open endpoints, physical map, logical
value root and substitution. A state row contains at most 19 scalar bindings,
three scratch facts and three output ledger pieces. A substitution row has at
most four capture-free `(binder,index-term)` replacements and source/target
scopes. Scope rows contain parent, namespace, loop binder/domain, hypothesis
owner and discharge target. Physical rows include ordered children, operation
fields and source origins. The table format does not permit a Boolean
"initialized", "source-correct" or "induction-succeeded" assertion as a premise.

A scratch store reserves explicit provenance/coverage/scope checks; bounds;
stored-value equality; checks for up to three disjoint frames; invalidation of
potentially overlapping facts; a singleton fact; compatible prefix join; exact
ledger preservation; and sequence linkage. An output store reserves bounds,
source equality, disjointness from up to three ledger pieces, singleton union,
join and exact sequence linkage. Scalar/load rules reserve operand membership,
i32 transition, exact term construction and bounds/initialized membership as
applicable. The proposed allocation is 32 proof rows per primitive instance.

A loop allocation reserves scoped domain/base checks, a fresh arbitrary-index
hypothesis, the actual body coverage root, step-state equality, successor and
exit substitutions, scratch weakening checks, full ledger equality, scope
non-escape and hypothesis discharge. It proposes 64 proof rows per loop. An
additional 128 rows reserve source/layout/row-major-injectivity premises,
complete two-case parity decomposition, source and final-output roots, and
necessary conjunction/link nodes. Pure region/affine/term constructor checks
are typed table obligations, not uncounted success flags. Counting *all* typed
rows as proof nodes gives a conservative node total independent of how a future
encoding classifies those local checks.

These 32/64/128 capacities are an explicit proposed rule expansion, **not**
measured row counts or an independently accepted completeness proof. In
particular, a fully instantiated graph must establish that all state-equality
premises and conjunction nodes fit these allocations. Reserving slots alone
does not prove their sufficiency. This remains part of F1; it cannot be hidden
by counting only the outer rule names.

With N, K and S above, the proposal gives the following table capacities. The
formulas deliberately charge fresh per-context values, rather than claiming
unproved cross-scope sharing:

| Table | Formula | Rows2 capacity | Bytes per row |
|---|---|---:|---:|
| Proof rows | `32N+64K+128` | 1,504 | 128 |
| Regions R | `2S+12K+3` | 85 | 96 |
| States | `2N+4S+6K+2` | 120 | 320 |
| Terms | `16R+4N` | 1,484 | 64 |
| Affines | `8R+2N+4K+8` | 774 | 64 |
| Substitutions | `4R+4N+4K` | 488 | 96 |
| Scopes | `3K+6` | 24 | 96 |
| Physical nodes | actual syntax | 22 | 160 |

Regions allocate two store results (singleton/join), three facts at each of four
loop contexts (base, arbitrary entry, successor, exit), and three global regions.
States allocate incoming/outgoing primitive states, four additional transient
store states, six linkage states per loop and initial/final roots. Each region
reserves a fresh 16-node expanded E (T uses fewer); each primitive reserves four
additional term nodes. Affines reserve four endpoints, two physical coordinates
and two logical value coordinates per region, two coordinates per primitive,
four loop substitutions and eight parity/layout entries. Substitution rows
reserve four contexts per region, primitive and loop. Scope rows cover three
local induction contexts per loop plus root/source/quantifier/parity scopes.
These are conservative reservation formulas; exact constructor sharing remains
unmeasured. Substitution cannot carry scalar data.

The total is 4,501 typed rows, below 16,384 proof nodes even when every data row
is charged as a proof node. Indices are below 8,192 (at most four decimal
digits). Term/source scalar literals and interval endpoints here need at most
seven decimal digits; source constraints need ten. Specialized affine
coefficients need at most five including sign; mathematical row-major offsets
and intermediate affine differences fit 31 magnitude bits. The row widths include
array delimiters, commas, signed decimal spellings, all listed references and
payloads; hashes occur only in the header. A 4,096-byte header/directory allowance
is added. Under the stated row allocations, the encoded-size upper bound is
440,352 bytes, below 524,288. The physical plan allowance is 3,520 bytes, below
262,144. These are **conditional analytical bounds**, not measured encodings.

### Peaks and integer widths

Materialize's completed-prior-rows fact, current-row prefix and newly stored
singleton coexist before joining: peak scratch facts **three**, not two. Rows2
likewise has current row, next prefix and singleton. Ledger previous rows,
current prefix and singleton need three pieces. Counting both collections gives
six active region facts, below 256, with at most six live pieces (below 1,024).
The 85 table-region allowance concerns persistent proof payloads, not active
machine facts. Empty rectangles denote empty sets and do not initialize reads.

Physical nesting is two; at most four lexical layers are needed when source and
quantified region binders are included. Parity cases are exactly two. Affine
expressions in these outlines have at most two varying atoms (with literal mod2
represented explicitly), below 16. The largest fully expanded scalar shape E
has 16 interned nodes and depth six; the proposed table capacity 1,484 is below
65,536. Substitution changes indices, not scalar association or scalar depth.
The source already obeys its 65,536-byte limit. An admitted source has 54
non-group expression nodes in the normalized family; up to 32 group wrappers
per node gives at most `54*33` expression visits per full traversal. Each
additional `require plan_workspace_bytes<=0;` requires at least 32 bytes, so
there are at most 2,048 source constraints. Source identifiers/comments and
whitespace remain byte-bounded ingestion, not additional scalar proof terms.

For all admitted dimensions, pitch is at most 8,193; coefficient/endpoint
products are below `2^28`, scalar producer/output values below `2^23`, and
outline dynamic counts below `2^28`. Source constraints are nonnegative i32.
Differences, interval arithmetic and the finite sums used here fit 31 magnitude
bits. No dimension-dependent product can silently wrap. Table IDs fit 13 bits;
coefficient/endpoint multiply operands need at most 14 bits. Every required
proof intermediate is thus within the frozen 256-bit bound. These statements
concern the hand derivations, not arbitrary adversarial certificates. Decimal
field lengths remain below the v2 78-digit ingestion limit; no v1 quota changes.

### Charged-work attempt and why it does not close F1

Consider a topological validator for the proposed fully materialized tables.
It checks each table row and each reference, performs interval and affine
arithmetic locally, and uses a bit trie for exact term-key interning. Each trie
bit examination and transition is charged; there is no assumed free hash-table
lookup. Congruence checks still validate every physical operation and each
materialized term; sharing does not erase obligations. This attempt does not
use a general term-DAG Cartesian product. Its conservative costs are:

| Category | Bound formula | Charged work |
|---|---|---:|
| Source admission/reconstruction | `8*(54*33+2048+6)+2048*6*31+16*4*31+32*T` | 461,088 |
| Proof references/coverage | `Q*(8*13+16)` | 180,480 |
| Affine normalization/bounds/parity | `A*(4*31+4*14*14+4*31+16)` | 811,152 |
| Term keys/intervals/comparison | `T*(2*8*31+4*31*31+8*31+16)` | 6,832,336 |
| Regions | `R*(12*13+16)` | 14,620 |
| States/ledger/facts | `V*(50*13+16)` | 79,920 |
| Substitution/capture checks | `D*(8*13+8*31+16)` | 179,584 |
| Scopes/hypotheses | `G*(16*13+16)` | 5,376 |
| Physical metrics/origins/coverage | `I*(8*31*31+16*31+16)` | 180,400 |
| Identity byte traversal/directory | `65536+4096` | 69,632 |
| **Total** | sum of all categories | **8,814,588** |

Q/R/V/T/A/D/G/I denote the table capacities above. Structural visits are included
in each row's added 16-unit allowance; integer comparisons use 13 bits for table
indices and 31 for mathematical values. Term rows reserve an eight-field
31-bit key with two charged trie actions per bit, four endpoint products for
interval multiplication, eight endpoint comparisons and 16 structural actions.
This deliberately applies the multiplication interval rule to every reserved
term row; it is very loose. Affine rows reserve four additions, four bounded
coefficient products, four endpoint comparisons and their structural work.
State rows check at most 25 `(binding,value)` pairs (50 references); region rows
check twelve references. Substitution rows check four replacement pairs and
eight scalar/index relations. Source admission reserves eight full visits,
six cap checks per source constraint, four checks on each of the 16 fixed
integer leaves and 32 group-wrapper visits per reconstructed term. The source
pass counts and 16-unit structural row allowances themselves need an actual
algorithm audit; they are conservative design allocations, not instrumentation
of the existing Python frontend. Cryptographic identity hashing is bounded byte
ingestion here, not an asserted machine-time or zero-allocation property.

This calculation is useful because it exposes rather than hides the missing
argument. It **does not establish a sub-million bound**, and its uninstantiated
row/algorithm allocations must not be promoted to exact evidence. To close F1,
construct the actual scoped graph (or finish a complete expansion proof), derive
reachable distinct term/affine/substitution instances and a charged memo/trie
algorithm for that graph, and include the source/identity/state costs. A result
above the quota is unavailable, not semantic invalidity. The present fix stops
at that precise unresolved obligation; C4–C11 stay blocked and no production
C3–C5 implementation is substituted for the missing C1 evidence.
