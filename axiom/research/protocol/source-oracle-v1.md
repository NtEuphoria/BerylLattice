# Original-source streaming oracle, research protocol v1

This O2 calculator consumes exact C2/v2 source bytes and an O1
`VerifiedInvocation`; it produces a complete existing state-v1 artifact. It
confers no O3 qualification, receipt, native acquisition or performance claim.
A caller-created `OracleResult`, including a well-typed frozen result, is not
qualification authority. The original parser and source admission frontend are
an explicitly shared trusted base with the compiler. Execution imports only
source model/profile, invocation transport, existing state artifacts and the
standard library; it uses no reference evaluator, plan, checker, selector,
emitter, native computation, optimizer DAG or schedule implementation.

## API and records

```python
evaluate_source_state(source_bytes: bytes, invocation: VerifiedInvocation,
                      destination: Path, *, profile: SourceProfileV2,
                      limits: OracleLimits) -> OracleResult
```

`OracleLimits` is frozen/slotted and validates exact positive integer counts,
rejecting bool, floats and values above these fixed ceilings:

| Field | Default and ceiling |
| --- | ---: |
| max_source_bytes | 65,536 |
| max_cached_input_bytes | 2,097,152 |
| max_scalar_evaluations | 1,000,000,000 |
| max_temporary_bytes | 268,435,456 |
| max_input_snapshot_bytes | 33,554,432 |
| state_limits | Existing `ArtifactLimits()` defaults |

The existing state ceilings are 1,048,576-byte aligned chunks, 16,777,216 bytes
per file, 268,435,456 aggregate bytes, 16,384 files, 268,435,456 logical state
bytes, and metadata of at most 1,048,576 bytes, depth 16 and 65,536 items. Each
nested limit may only tighten. The API revalidates both records at entry,
including nested state fields, even after unsafe object-field mutation.
`SourceProfileV2` must be the exact supported profile. Invalid configuration or
a non-Path destination raises `ValueError`; these are caller programming errors.
The optional `deadline_monotonic_ns` is an exact integer in [0, 2**63-1].
`cancelled` is optional and callable; each call must return exact bool. Exceptions
from user cancellation code propagate unless they are one of the explicitly
handled operational allocation/recursion/I/O failures.

`OracleResult` is frozen/slotted with status, optional state manifest and
first-bad index; exact source, family, specialization, v2 invocation and separate
state-v1 invocation hashes; the counters below; and a bounded diagnostic code.
Its constructor validates status, optional fields, hash spelling, exact
nonnegative counters and the complete/incomplete field relationship. Only
`success` and `input_precondition_failed` have a state manifest and all five
identities; only the latter has a first-bad index. Complete results have no
failure detail. Incomplete results have no state manifest or first-bad index,
and retain only identities already validated and partial observable counters.
Diagnostic codes are 1–128 characters without source/input data or exception
representations.

## Admission and scalar meaning

The supplied exact immutable bytes are reparsed with `admit_source_v2`; source
byte limits are explicit. Changed unsupported equations return
`unsupported_source` without input acquisition or AST work. The invocation must
have exact `VerifiedInvocation` type, pass its full public `revalidate()`, and
match the supplied source bytes, profile, dimensions and all three source
identities. An admitted source paired with another invocation returns
`invalid_invocation`.

Only after reservation and exclusive destination creation, the public input
blob traversal is copied to an anonymous `TemporaryFile`. This traversal itself
fully revalidates the blob. O2 independently checks acquired length, whole-input
SHA-256, i32 alignment and every scalar's admitted interval, row-major. At most
three unfinished scalar bytes carry between generic blob blocks. It retains
the earliest failing index but finishes all input scanning. Rejected input calls
no expression visitor, including declaration/bound evaluation, and preserves
all original input and all initial-output values, including nonzero canaries.
Initial output is traversed through the verified public transport in this
branch, supporting scalar-splitting byte chunks.

After valid preflight, evaluate original shape declarations, input dimension
expressions and equation axis lower/upper expressions in declaration/axis
order. Bind declared names in separate scalar and tensor namespaces. Tensor
reads validate arity, exact i32 indices, declared dimensions/bounds and checked
row-major offsets. Lazy producer reads bind that declaration's axis names and
revisit its original body. No producer or output cells are retained. Output
coordinates are generated in declared Cartesian order, with rank-sized nested
generators rather than product-sized collections. The currently admitted family
has positive H/W, exactly one producer and one output and no extra dead producer
arithmetic; every producer coordinate is demanded by the outputs. This reasoning
does not extend to arbitrary programs/dead computations.

Each original literal, name, group, binary operator, read and index-expression
node is charged before dispatch. Evaluate binary left before right and indices
in source order; use exact Python arithmetic, checking signed i32 at every
node, including groups/reads. Producer rereads revisit all their body nodes.
No canonicalization/ungrouping is used for execution. Group-only changes can
increase work without changing values. The first over-budget node is not
dispatched and the retained count never exceeds its configured limit. The
visitor uses Python recursion; excessive original grouping or recursive
execution exhausts that bounded runtime resource as incomplete
`resource_limit`, never semantic input rejection. The frontend may itself
reject source before execution.

## Resource reservation and cache

`max_temporary_bytes` is a **logical temporary payload quota**, not filesystem
block allocation, physical free-space reservation, an OS guarantee, or RSS.
Before creating the operation/snapshot or acquiring any input blocks, reserve
shape-specific input snapshot bytes plus full encoded input/output state bytes
plus the configured maximum state-manifest bytes. Do not credit content
deduplication. The conservative whole-envelope bound with default metadata is
33,554,432 + 67,108,864 + 1,048,576 = 101,711,872 bytes (97 MiB); actual admitted
shapes have smaller state payload. The existing O1 invocation revalidation
necessarily reads its source/buffer closure before this reservation; this is
trust-boundary verification, not O2 snapshot acquisition.

Also preflight no-dedup state chunk count plus one manifest against max_files;
all projected individual chunk lengths and the manifest against max_file_bytes;
logical bytes against max_logical_bytes; and full logical chunk bytes plus a
conservative manifest bound against max_aggregate_bytes. The manifest projection
uses the longer rejected-input status and largest possible first-bad index,
fixed-size hash/path strings and actual offset/length digits. It counts all JSON
items (11 per chunk plus exact base-record items) and checks the maximum nesting
depth of 3, the writer's additional chunk-item admission, and maximum encoded
metadata bytes. This precedes acquisition even when eventual equal chunks would
deduplicate. Existing write_state checks file/aggregate closure quotas late;
O2 does not rely on that late check for operational admission. Manifest memory
is bounded by state metadata limits; no projected chunk-record collection is
built by O2. State writer/verifier retain their bounded metadata records.

The anonymous snapshot has a pinned descriptor and is local to one invocation.
Random scalar access uses exact-length `os.pread`, little-endian decoding and
an LRU of at most two i32-aligned byte chunks, evicting before allocating a new
chunk. The minimum cache budget is 4 bytes; budgets 4–7 use one 4-byte chunk.
Larger budgets use up to two chunks of size
`min(1048576, max(4, floor(floor(budget/2)/4)*4))`. Unused odd/alignment bytes do
not increase retained payload. Cache payload never exceeds the configured
budget. It counts only retained random-reader bytes; it excludes parser/AST and
source objects, O1's bounded transport/verification buffers, the ingestion block
and aligned decoding buffer, at most three carry bytes, the separate 65,536-byte
sequential input-preservation buffer, state-writer output buffer, metadata and
Python allocator overhead. It makes no hard heap or RSS guarantee.

## Publication and failures

Pin each existing destination ancestor with descriptor-relative NOFOLLOW
opens. Exclusively create a private mode-0700 destination; do not overwrite any
existing destination. Create `.pending` inside it, copy/preflight input and
stream the complete state there with the same validated explicit state limits.
Verify the staged state again and compare full metadata, including the explicit
state-v1 invocation identity. Revalidate the entire original invocation after
all generation and verification. Allocate the completed result and close the
snapshot, then poll cancellation/deadline immediately before the atomic
`.pending` → `completed` rename in the pinned directory. The returned manifest
is `destination/completed/state.json`.

The state metadata's logical semantics hash is the C2 **specialization** hash,
with original input and initial-output hashes. Require its state-v1 invocation
hash to equal `invocation.state_v1_invocation_sha256()`; the exact-source v2
invocation hash is a separate result field. Renamed/grouped sources may share
semantic state identities while retaining distinct exact-source pins.

No cancellation poll or fallible semantic verification follows publication.
Cleanup after the commit point cannot relabel a committed artifact incomplete.
Before publication all normal error paths close the anonymous snapshot and
owned directory descriptors and remove the owned pending subtree/destination;
no completed manifest is returned. Cleanup is best effort if the filesystem
itself refuses close/removal. Stable files/directories and no hostile same-UID
writer are the O1/state assumption; this is not isolation from a same-UID actor
racing names/bytes or sabotaging cleanup. Existing artifacts are never removed.

| Outcome | Phase and meaning |
| --- | --- |
| success | Fully verified complete state from valid input |
| input_precondition_failed | Full input scan completed, earliest invalid scalar, all original buffers preserved |
| unsupported_source | Exact-byte source admission failed |
| invalid_invocation | Typed boundary/revalidation or source match failed; also acquired bytes differ in length/hash/alignment |
| work_limit | Next original AST node exceeded fuel |
| cancelled / timeout | Cooperative callback/deadline poll failed |
| resource_limit | Logical/file/metadata quota, recursion/i32 operational integrity failure, ENOSPC/EDQUOT/EFBIG |
| allocation_failure | MemoryError |
| io_failure | Other snapshot/state/storage or artifact verification failure |

Safe O1/state helpers sometimes wrap OSError in ValueError. Classification is
by phase: errors in explicit invocation revalidation are invalid_invocation;
after a valid boundary, public blob iteration or state writer/verifier
ValueErrors are incomplete artifact I/O failures. Their explicit exception-cause
chain is inspected so wrapped ENOSPC/EDQUOT/EFBIG remains resource_limit. Raw
OSError uses the same storage mapping. Independent acquired length/hash
mismatches remain invalid_invocation. Unrelated interpreter/programmer errors
propagate and trigger prepublication cleanup; ValueErrors from equation/emission
code are kept distinct from safe-helper ValueErrors. None of these errors is
encoded as a completed semantic input rejection.

Polling is cooperative: at entry, before/after invocation verification, every
reservation chunk, copied input block, preflight scalar, original AST dispatch,
random read, sequential snapshot block/scalar, initial-output block/scalar,
emitted scalar, between writer/verifier passes and immediately before publish.
O1 full revalidate/iter_bytes verification and state write_state's internal final
verification plus O2's extra verify_state are opaque noninterruptible helper
passes. Parsing/admission, bounded OS writes/reads and snapshot flush/close also
have no callback inside. A hard wall deadline requires a supervised worker;
the API does not promise one.

## Observable counters and scope

| Counter | Unit |
| --- | --- |
| scalar_evaluations | Original AST node dispatches charged before evaluation, including declarations/bounds and repeated lazy bodies |
| input_preflight_scalars | Complete i32 values checked from acquired row-major input bytes |
| emitted_state_scalars | Scalar values yielded to the state writer, input role then output; partial output counters do not imply durable files |
| input_read_scalars | Logical scalar read attempts by source input tensor evaluation, excluding preflight/preservation |
| input_snapshot_bytes | Bytes reported written by the private snapshot; includes a partial write count before short-write failure |
| acquired_input_bytes | Input block bytes yielded to O2 by the public blob traversal |
| snapshot_read_bytes | Actual byte lengths returned by private pread calls, including preservation/cache fills and short reads |
| cache_misses | Successful exact-length random-reader cache fills |
| peak_cached_input_bytes | Maximum retained random-reader payload bytes |

On complete execution, preflight=P, emitted=P+O, snapshot-written/acquired=4P.
These local counters exclude O1/state internal reads/hashes, source parsing,
metadata operations, filesystem caching/block traffic and reference/testing
reads. O1 entry/final invocation validation traverse the source/input/output
closure, input iteration adds full blob revalidation and yielding, rejected
output iteration similarly verifies/yields, write_state performs full closure
verification and O2 verifies again. They are not complete campaign physical or
logical I/O accounting; O5 requires its own accounting boundary.

Portable tests retain independent small-reference comparisons only for P<=256,
all invalid positions/extrema/canaries, renamed/grouped original nodes, exact
fuel, 7-byte blob boundaries, 16-byte state chunks, tiny cache eviction, complete
identities, import guards and injected operational failures. Disclosed all-zero
and all-1023 32×32 controls check every input/output scalar against known 4 and
4,194,304 outputs. The separate 128×128 disclosed synthetic timing checks are
feasibility observations only. O2 does not widen v1 reference admission, run fresh
holdout or qualify 2048×2048/native performance.

## O3: explicitly selected qualification and independent receipt verification

O3 adds `research/oracle_receipt.py`. A producer's completed result is a claim;
serialization does not establish that its source was executed. The verifier
executes the fixed imported `source_oracle.evaluate_source_state` exactly once
for each newly issued oracle and compares all candidate input/output scalars to
that independently generated state. `success` and `input_precondition_failed`
are the only completed outcomes. An operational failure never becomes input
rejection or a verified expected state. Rejection comparisons include every
initial-output canary and preserved input cell, including the final chunk.

The public boundaries are:

```python
select_oracle_qualification(approval_manifest, *, approved_root_sha256,
                           live_roots, scratch_directory,
                           limits=OracleQualificationLimits())
produce_oracle_receipt(result, qualification, destination)
verify_oracle_receipt(receipt, source_bytes, invocation, qualification, *, limits)
```

`approved_root_sha256` has no default, environment fallback or product-installed
value. It comes from an independently selected external controller workflow.
The approval manifest's own review assertions, a caller-constructed result or
public dataclass, and passing unit tests cannot select that root. No receipt
command, module, executable, callback or policy is executed. Descriptive test
argv is evidence data only. Cancellation is an explicitly trusted caller
control from `OracleLimits`, never a receipt field.

### Closed, acyclic evidence graph

All documents use bounded canonical JSON: sorted keys, ASCII encoding, exact
integers, no floating numbers, duplicate keys, missing/unknown fields or unsafe
paths. Digests are lowercase SHA-256. References resolve beneath the containing
approval/receipt root; blob chunk paths resolve beneath their blob manifest.
No arbitrary recursive reference discovery is performed.

`DocumentRef` has exactly `{path, sha256, byte_length}`. `BlobRef` has exactly
`{path, manifest_sha256, sha256, byte_length}` and refers to an O1
`axiom-blob-v2` manifest. A document digest covers its complete canonical bytes;
it is not embedded in the same document.

| Document schema | Exact fields in addition to `schema` |
| --- | --- |
| `axiom-oracle-approval-v1` | `qualification: DocumentRef`, `test_evidence: DocumentRef`, `review: DocumentRef` |
| `axiom-oracle-qualification-v1` | `entrypoint`, `runtime_assumption`, `source_profile`, `versions`, `python`, `inventory`, `trusted_base: DocumentRef` |
| `axiom-oracle-trusted-base-v1` | `assumptions`: nonempty list of bounded nonempty strings |
| `axiom-oracle-tests-v1` | `qualification_sha256`, `inputs`, `runs` |
| `axiom-oracle-review-v1` | `qualification_sha256`, `test_evidence_sha256`, `reviewer`, `decision`, `unresolved_findings`, `record: BlobRef` |
| `axiom-source-oracle-receipt-v1` | `qualification_sha256`, `approval_sha256`, `source_sha256`, `family_semantics_sha256`, `specialization_semantics_sha256`, `source_profile`, `H`, `W`, `invocation_sha256`, `state_invocation_sha256`, `status`, `first_bad_index`, `expected_state: DocumentRef` |

Qualification `entrypoint` is exactly `source_oracle.evaluate_source_state` and
`runtime_assumption` is `trusted-fresh-python-in-process-v1`. `source_profile`
is exactly `asdict(SourceProfileV2())`. `versions` is exactly:

```json
{"ast":"original-source-ast-v1","invocation":"axiom-invocation-v2","oracle":"source-oracle-v1","source_admission":"axiom-source-v2","state":"axiom-state-v1"}
```

These are descriptive qualification tags, not a new wire-format API for the
existing AST. `python` has exactly `implementation` (`cpython`), `version`
(the current exact integer `[major, minor, micro]`) and
`executable_logical_path`. Inventory entries have exactly `role`, `logical_path`
and `blob: BlobRef`, ordered uniquely by normalized logical path. Runtime roles
are `implementation`, `python_executable`, `stdlib` and `runtime_library`;
exactly one entry is the actual resolved current executable. Logical paths
begin with an explicitly declared `repository`, `python` or `system` root.
Selected roots are absolute existing nonsymlink directories. Host absolute paths
are not serialized. Relocation requires the actual bytes and loaded origins to
match the selected roots.

Test `inputs` use the same entry shape with roles `test_source`,
`test_comparator`, `fixture` and `protocol`. Independent review must require all
actual sources/helpers/fixtures/protocols used in the claimed runs, including
O3/O2/synthetic receipt tests and their comparators. A run has exactly
`command_id`, `argv`, `mode`, `tests`, `passed`, `failed`, `errors`, `skipped`,
`exit_code` and `log: BlobRef`. Counts are exact nonnegative integers; their sum
must agree, at least one test must pass, failures/errors/exit status must be
zero. `o3`, `source_oracle` and `synthetic_receipts` are each required in
`normal` and `optimized` modes; O3 cannot claim skipped required tests. Logs and
review must support the actual execution claims; plausible counts alone do not
prove execution. Review requires bounded nonempty `reviewer`, `decision` equal
to `approved`, and an empty `unresolved_findings` list.

Prepare immutable implementation/runtime/trusted-base blobs and the qualification
document first. Execute the required tests against that exact subject and retain
actual logs and every evidence input. Next write test evidence referring to the
qualification digest. A fresh independent reviewer reviews the exact subject
and evidence and writes a retained review record/document. Finally assemble the
approval manifest, then have the external controller independently select its
digest. This acyclic sequence avoids self-hashes and self-review. O3 supplies no
production auto-qualification writer or default approved root. Temporary unit
fixtures explicitly use synthetic test/review assertions and grant no actual
production qualification.

### Actual runtime binding and limits of that binding

Inventory actual complete source bytes for O3, O2, state artifacts, and
`axiom.__init__`, model, frontend, source profiles, invocation and artifact
chunks, including every existing permitted repository `__cached__` file. Use
trusted cache-free source roots if caches are not included. Disable future
bytecode writes before capture (`sys.dont_write_bytecode = True`); `-B` by itself
does not prevent reading existing bytecode. The controller must prevent later
unapproved caches/import hooks from becoming authoritative.

The complete installed non-site/non-dist standard-library tree is walked through
descriptors without following symlink entries. Existing permitted bytecode is
included. The actual resolved `sys.executable` is hashed, not merely a version
string; this environment's executable exceeds 16 MiB and is retained with O1
chunks. Linux executable-file mappings are inspected from `/proc/self/maps`,
checked against device/inode, and included alongside actual loaded module
origins. Unresolvable mappings/origins make qualification unavailable. Builtin,
frozen and vDSO/kernel components remain explicit runtime assumptions. A nominal
`sysconfig` libpython name is not an observed library and must not be fabricated.
Revalidation repeats actual runtime enumeration and rehashes retained/live bytes.

The external controller starts a trusted Python process and selects/imports
reviewed implementation/runtime files, for example using `python -I -S` and
explicitly installing approved repository roots in `sys.path`. O3 has no child
launcher. Tests may launch a fresh process as a control; that process selects an
explicit temporary root and executes O2 again. Trust includes shared parser,
model, profile and state primitives, Python/runtime/OS correctness, trusted
controller/reviewer, honest loaded code and stable files. Reflective mutation of
private issuer tables, monkeypatching loaded functions/code objects, hostile
interpreter/OS, native injection and hostile same-UID read races are outside this
boundary. Source hashing cannot attest already monkeypatched in-memory code.
This is neither process isolation nor cryptographic attestation, a correctness
theorem, physical instrument qualification, native admission or O4/O5 acceptance.

### Storage, publication and lifetime

Qualification closure has a separate 536,870,912-byte ceiling; semantic closure
has a 268,435,456-byte ceiling. Both include metadata and every actual unique
retained file path, with at most 16,384 files, 16,777,216 bytes/file,
1,048,576-byte chunks and metadata at most 1,048,576 bytes, depth 16 and 65,536
items. Equal bytes at distinct retained paths count separately. Limits may only
tighten; bool is not an integer. Metadata/stat references are precharged before
bulk reads, including candidate state before invoking the state-v1 verifier.
Unknown schema/reference types cannot disappear from the ledger.

The producer reparses a complete state, validates exact result types/identities
and diagnostic counters, and preflights the full copy plus exact receipt bytes.
It copies every closure member under an exclusively created destination's
`.pending/state/` without hardlinks, verifies the copied state and original pins,
then renames `.pending` to `completed`. Existing destinations remain untouched.
It returns only `OracleReceipt(manifest_path, manifest_sha256)`, a value with no
verification authority. A structurally valid false complete claim may serialize;
it fails independent source verification.

Before execution the verifier reserves a live slot, all existing live anchors,
the candidate closure and a new no-dedup anchor. For `P=(H+1)*(W+1)`, `O=H*W`,
reserve state bytes `S=4*(P+O)`, snapshot `I=4*P`, maximum selected manifest bytes
and `ceil(4*P/chunk)+ceil(4*O/chunk)+1` anchor files. O2 independently checks its
exact metadata/items/depth/per-file projection before its own acquisition/writes;
O3 does not call a private O2 helper or widen its quotas. Temporary logical disk
payload is jointly bounded by selected operation and O2 limits at at most
268,435,456 bytes: `I+S+maximum_manifest+O3_private_metadata`. O2 receives only
the remaining allowance after O3 private metadata. An O2 manifest is counted
once. These are logical disk-payload bounds, not RSS/block-allocation/free-space
claims. Conservative maximum-manifest reservation may reject a tight budget.

Exact source/family/specialization, v2 invocation and explicit
`state_v1_invocation_sha256()` identities remain separate. The independently
generated state is the anchor; candidate-selected output never replaces it.
Immediately before issuance, candidate, anchor, invocation and qualification
are rechecked against original pins. Trusted cancellation callbacks run before
the last rehashes so final callback mutations cannot publish; deadline is checked
again without invoking a callback. Reentrant/concurrent operations on a selected
qualification fail explicitly through a nonblocking session guard.

At most one qualification and sixteen child oracles can be live, subject to
stricter selected limits. Their independent retained anchor closures share one
semantic budget. Handles have exact issuer-object identity, no public success
constructor and no serialization-based restoration. `expected_state` returns a
freshly reconstructed state; mutating its dataclass or inventing an empty closure
cannot change issuer pins. `revalidate()` rehashes actual candidate, anchor,
invocation and qualification/live files without executing the source AST again.
A fresh process must execute source verification again.

`close()` invalidates authority before deleting owned artifacts, is idempotent,
and supports context management. Parent close invalidates children. Failed
cleanup is reported, retains its conservative storage debt, and blocks a new
session until owned cleanup succeeds; retrying close grants no authority.
Cleanup paths and closed state come from private issuer records bound to the
exact handle object, never from caller-writable handle fields. Closed retries
use the original nonblocking session guard; live child authority is rechecked
after acquiring it. Parent closure transfers failed child cleanup to the parent
and coalesces descendant paths beneath owned cleanup roots. Successful removal
retires those path claims and their storage debt exactly once. External producer
debts remain retryable even after scratch cleanup succeeds. Closed-handle records
use weak references and retain no verification authority.
Absent owned paths are harmless. No fallible validation follows issuer-table
commit. Cancellation, timeouts, resource/I/O/allocation failures, state mismatches
or late mutations leave no newly issued handle or published partial receipt.
