# Checked Core runtime buffer boundary, version 1

Status: B1 executable specification, not a native implementation or qualification.
The source profile is `axiom-stencil-fixed-buffer-v1`, the private host contract
is `axiom-core-buffer-host-v1`, and the surrounding artifact/protocol route is
explicitly v2. All existing v1 interfaces, admission, hashes, canonical bytes,
replay and native-unavailable behavior remain unchanged.

## Source, sizes and arithmetic

Consume `axiom.source_profiles.admit_source_v2(source_bytes, *, profile,
limits)` with `SourceProfileV2()` and `SourceLimitsV2()`. Always admit retained
actual source bytes; an `AdmittedLoopKernel` object or caller validation bit
cannot validate a native invocation. B1 does not define a second admission API.
Source H/W are fixed positive literal specialization parameters; runtime data
and initialized output buffers reuse that specialization.

```
1 <= H,W <= 8192
P = (H+1)*(W+1) <= 2^23
Q = H*W
input: i32[P], admitted values 0..1023
producer(r,c) = (input(r,c)+1) * (input(r,c)+1)
output(r,c) = ((producer(r,c)+producer(r,c+1))
                +producer(r+1,c))+producer(r+1,c+1)
0 <= scratch_capacity_cells <= P
```

The parsed scalar AST, including association, controls computation. Every
source and physical scalar operation is checked i32, including dead operations.
Producer bounds are 1..1,048,576; successive output sums are bounded by
2,097,152, 3,145,728 and 4,194,304. Both source additions preceding the
producer multiplication are source operations. No index normalization permits
reassociation of source equations.

Compute P, Q, `4P`, `4Q`, `4(P+Q)` and `4*scratch_capacity_cells` with checked
wide host arithmetic before allocation or narrowing. Counts must fit i32 and
byte extents/additions must fit target `SIZE_MAX` and explicit resource limits.
Charge every reserved scratch cell even when unused; descriptor length and
capacity equal exact reserved capacity. Intersect the source workspace cap
with execution/resource caps. Missing budgets/observations do not become zero.
The engineering envelope gives one complete input/output state strictly below
64 MiB and scratch at most 32 MiB; these are not native memory promises.

| H | W | P | Q | input bytes | output bytes |
|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 4 | 1 | 16 | 4 |
| 8191 | 1023 | 8,388,608 | 8,379,393 | 33,554,432 | 33,517,572 |
| 8192 | 1 | 16,386 | 8,192 | 65,544 | 32,768 |
| 2049 | 2047 | 4,198,400 | 4,194,303 | 16,793,600 | 16,777,212 |
| 2048 | 2048 | 4,198,401 | 4,194,304 | 16,793,604 | 16,777,216 |

The last row has 33,570,820 state bytes. H=8192/W=1023 exceeds P's cap;
H=8193, W=8193 or either zero is rejected. Large cases here are arithmetic-only;
B1 creates no primary-shape input or held-out data.

Mathematical index validity is a separate proof from native representability.
Before Core emission independently prove every emitted constant, product,
affine sum, flattening intermediate, loop comparison/update, terminal counter,
exclusive-bound conversion and modulo operand/result. Include admissible
high-bound empty loops. A final in-bounds address proves none of its evaluation
intermediates. For `K*r-K*r+c`, K=1073741824 and reachable r=2, normalize and
prove all actually emitted operations or return typed
`NativeLoweringUnsupported` with node/source origin and reason. Preserve the
independently valid logical/physical checker result. Negative mathematical
modulo-two arguments require a proved equivalent supported lowering or the
same typed unavailability; Core/C remainder is not Euclidean modulo there.
Do not use wider unchecked expressions, casts or undeclared intrinsics. No
silent saved-plan substitution is allowed.

## Invocation ownership and ordered scopes

The process protocol exposes only one owned checked invocation. It supplies
retained state references and a matching compiled specialization, never raw
pointers, a preflight-success bit or a body-helper operation. Helpers are
private to the worker. There are no exported aliases, callbacks into callers,
concurrent accesses or ownership changes between preflight and body. Absence
of a lifetime/immutability guarantee blocks the route.

Preparation materializes owned input and fully initialized output, validates
transport hashes and initializes the invocation record in a separate paid
scope. Each allocation records unique identity/generation, role, live state,
base, logical/initialized/reserved cells, byte extent, alignment and lifetime.
Release invalidates the handle. Addresses alone do not establish identity.
Input/output/nonempty scratch must be distinct whole owned allocations, with
no offset views; never compare unrelated C pointers relationally to prove this.

The checked-call timer encloses exactly the following ordered work:

1. Constant-sized metadata guards: live handles/generations, exact input/output
   counts and capacities, specialization identity, initialized extents,
   alignment and disjoint allocation identities. Metadata rejection precedes
   any Core access.
2. One generated Core row-major preflight, returning -1 for success or the
   first invalid offset in 0..P-1. Any other return is a protocol failure.
   Every valid-input cell is scanned; rejection stops at the first invalid cell.
3. On input rejection, preserve complete input and original output, check
   applicable descriptors, end the timer and acquire full state. No scratch
   allocation, scratch initialization or body invocation occurs.
4. On valid input, check scratch requirements, allocate exact nonzero capacity
   through the operation allocator and zero every scratch cell before borrowing.
   Inline uses initialized `{NULL,0,0}`, with zero allocation requests.
5. Invoke the Core body with borrowed descriptors and immutable input.
6. Check input/output/scratch data pointer, length and capacity against recorded
   metadata in constant space; mutation is an integrity failure.
7. Free scratch through C cleanup using the original host allocation record,
   never the possibly corrupted borrowed descriptor. Retain allocator evidence.
8. End the timer. Only then acquire all final input/output bytes and perform
   full-state hashing and independent source comparison.

There is no second O(P) input scan/hash in the checked-call timer. Full input
comparison after execution is mandatory. A second-preflight design requires
an explicit contract revision charging both scans. Input/output cleanup,
acquisition, comparison and end-to-end paid work have distinct scopes. Record
actual timing boundaries; B1's fixture events establish order, not timing.

Ordinary malloc/calloc i32 alignment suffices initially. Any stronger alignment,
rounding, headers and padding must be separately checked/charged. Logical
workspace, requested operation heap, allocator reservation/slack, stack, caller
buffers, collector storage and RSS are separate quantities. No zero-size
allocation or realloc is part of the kernel path. Scratch OOM after preflight
preserves output. Preparation OOM occurs before semantic invocation. Recoverable
paths explicitly free scratch; Core clear/defer are not cleanup mechanisms.
A killed worker receives supervisor reclamation, never a successful per-call
cleanup receipt.

## Result records and independent evidence

| Record class | Meaning | Completed semantic state? |
|---|---|---|
| semantic success | valid input; complete final input/output acquired | yes, status `success` |
| semantic source rejection | exact first invalid index; complete input and original output preserved/acquired | yes, status `input_precondition_failed` |
| boundary | bad handle, generation, alias, shape, initialization, alignment or specialization | no |
| preparation resource | input/output preparation allocation fails | no invocation |
| execution resource | scratch OOM or explicit execution budget exhaustion | no |
| infrastructure/execution | unavailable dependency, trap, signal, timeout, cancellation, protocol contradiction | no |
| integrity/evidence | descriptor mutation, missing/partial acquisition, failed state binding | no |
| independent comparison mismatch | acquired complete state differs from source oracle | no accepted correspondence |

NativeRunV2 completion remains the shared enum: `complete`, `boundary_error`,
`resource_error`, `unavailable`, `timeout`, `cancelled`, `process_error`,
`acquisition_error`, `integrity_error`. `complete` includes an acquired normal
source rejection; it does not assert oracle equality or performance admission.
An independent comparison failure is an evidence/correspondence failure, not a
third source status. The B1 combined fixture uses a local `comparison_error`
label for this later gate, not an extension to NativeRunV2. Never synthesize
completed state from partial output. Correctness, abstract storage, allocation,
timing and publication remain separate gates.

Retain separate exact `source_sha256`, shape-independent alpha-normalized
versioned `family_semantics_sha256` and H/W-specific versioned
`specialization_semantics_sha256`. Constraints/effective-cap and objective
have separate canonical identities bound to checking/replay. Ordered source
paths, generated Core/C, compiler pins, binaries, plans, certificates and runs
have distinct identities. Build identity includes source, loop candidate,
constraints, target and toolchain, and excludes runtime values/seeds.

Consume O1's invocation/state transport and O3/O5's oracle/acquisition protocol;
do not create competing manifests. Every invocation acquires and compares all
bytes before any state sharing. Semantic and qualification stores have actual
immutable inventories capped separately at 256 MiB and 512 MiB. Shared format
bounds are 1 MiB chunks, 16 MiB maximum physical file, 16,384 files per store,
1 MiB metadata documents, depth 16 and 65,536 items. Logical blobs larger than
a file require complete contiguous chunked representation, not truncation;
the 16,793,600-byte primary input cannot fit one old v1 file. Verify actual
inventory/hashes before and after use. Bind any materialized executable to
complete inventoried content, byte identity, mode and explicit original/copy
paths, then revalidate it. Missing/oversized closure is unavailable/resource
limited. No relocation or hostile same-UID immutability claim follows.

## Core helpers and target assumptions

Hand-written [tiny helper](../tests/fixtures/core_native_v2/tiny-1x2.be):

```text
fn ax_preflight(let input: List<i32>) -> i32
fn ax_body(let input: List<i32>, inout output: List<i32>,
           inout scratch: List<i32>)
```

The tiny specialization is H=1/W=2, P=6/Q=2, materialized scratch=6.
Only integer range loops, checked i32 scalar operations/temporaries and List
get/set/length operations are permitted. No owning local List, growth, clear,
descriptor replacement, external storage, escaped references, concurrency or
unsafe blocks. Reads and writes are separate statements because
`xs.set(i,xs.get(j))` overlaps receiver borrowing. Mutating schedules use
integer ranges rather than collection foreach. The fixture has no witness
values, source generator dependency, main entry or public helper operation.
Its explicit JSON cases are independently hand-worked: input 0..5 produces
[46,74]; all zeros produce [4,4]; all 1023 produce [4194304,4194304]. Invalid
cases preserve both distinct nonzero sentinels [-99,77].

The initial target is Linux/x86-64, C11, eight-bit bytes and four-byte int32_t,
with the pinned Core `0a678b4ae6d41190c4f5a8bf063caba05759d20d`.
Include unchanged `emit-c` output in the same translation unit; actual typedef
is `be_t_List_3ci32_3e`, with fields `int32_t *data; int32_t len; int32_t cap;`.
Expected function-pointer types are:

```c
int32_t (*)(const be_t_List_3ci32_3e *)
void (*)(const be_t_List_3ci32_3e *, be_t_List_3ci32_3e *, be_t_List_3ci32_3e *)
```

Require `_Generic` assertions for actual helper function-pointer types and all
field types, and `_Static_assert` for CHAR_BIT=8, sizeof(int32_t)=4, pointer
size=8, data/len/cap offsets=0/8/12, descriptor size=16 and alignment=8 on this
target. These are expected target assumptions for B2 to qualify; B1 does not
assert a successful compile. Top-level parameter restrict does not weaken
pointer/const/pointee type checks. A const descriptor pointer does not make its
data target const: ownership, checked Core and complete postcomparison carry
that obligation.

Bind actual qualified names `axiom_buffer_fixture.ax_preflight` and
`axiom_buffer_fixture.ax_body`, deterministic generated C symbols, actual
typedef/signatures/layout, source order, Core pin, generated Core/C hashes and
target/ABI version in the private B2 manifest. Missing or changed declarations
must fail compilation. No regex rewrite, descriptor cast, patched generated C
or general C parser is an ABI. If this cannot fail closed, B8 requires a
separately reviewed generated header/export manifest. A future shared library
needs hidden helpers and an inspected export allowlist. Symbol containment is
not a hostile same-process security sandbox. Runtime regeneration and the
selected compiler/config/known-component closure remain bound; this does not
fingerprint every SDK/linker dependency or establish a hermetic toolchain.

## Source review and executable scope

Reviewed against pinned Core: `src/back/c_backend.c` List declaration/get/set
and parameter lowering; `src/sema/ownership.c:279` whole-call receiver borrows;
`src/sema/storage.c:293` mutating iteration; `runtime/beryl_rt.h` checked List
access; and `docs/advanced/P1_STORAGE_ADMISSION.md` lifetime limitations.
Cross-checked the shared plans' 01 sections 2.1–2.6 and B1; 03 O1/O2/O5 exact
state lengths, source status and complete acquisition; 04 M1/M2 paid scopes,
no dummy allocation and resource separation. The preserved local restoration
and exact repository pins are recorded in
[the execution baseline](../../docs/reviews/axiom-scalability-baseline.md).

`tests/support/buffer_contract_v2.py` is deliberately a test-only Python
adapter: arbitrary-shape size calculations consume C2, while execution is
restricted to the tiny 1x2 specialization. Callback operations really read,
allocate, initialize, mutate, release, acquire and independently compare via
the existing original-AST reference evaluator. Faults and bad-proposal controls
exercise ordering and preservation; they do not qualify C pointer ownership,
Core admission, generated C signatures, allocation interception or clocks.
The inline callback case establishes the zero-allocation boundary contract,
not a second Core fixture or a compiled inline schedule. Production execution
and qualification begin at B2/B3. No compiler or production lifecycle change
is part of B1.

Run from `axiom/`:

```sh
PYTHONPATH=src python -m unittest tests.test_core_buffer_contract_v2 -v
PYTHONPATH=src python -O -m unittest tests.test_core_buffer_contract_v2 -v
```
