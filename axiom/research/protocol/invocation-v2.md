# Bounded blob and exact-source invocation transport v2

This production transport is independent of an oracle, physical plan, emission,
executable, acquisition, run, semantic outcome, comparison, and measurement.
Neither a blob nor an invocation establishes execution or native admission.
The production modules import no research modules. All v1 formats and limits
remain unchanged.

## Public Python interfaces

`axiom.artifact_chunks_v2` provides frozen `BlobLimits`, `BlobReference`,
`ChunkReference`, and `VerifiedBlob` records and:

```python
write_blob(blocks: Iterable[bytes], byte_length: int, directory: Path,
           *, limits: BlobLimits) -> BlobReference
verify_blob(reference: BlobReference, *, limits: BlobLimits) -> VerifiedBlob
read_manifest(path: Path, *, limits: BlobLimits) -> tuple[object, str]
canonical_json(value) -> bytes
```

`BlobReference(manifest_path, manifest_sha256, byte_length, sha256)` names a
manifest and binds its exact bytes, logical byte length, and whole-content
SHA-256. Paths in returned records are absolute. `ChunkReference` contains
`offset`, `byte_length`, `path`, and `sha256`. `VerifiedBlob` exposes `reference`,
`limits`, an immutable tuple `chunks`, `byte_length`, `sha256`, and diagnostic
`cached_chunk_count`. `revalidate() -> None` reopens and hashes the complete
manifest/chunk closure, comparing it with the bound reference and chunk records.
`iter_bytes() -> Iterator[bytes]` first revalidates and then reads/hashes every
actual ordered chunk; callers must exhaust the iterator before accepting a full
acquisition. `read_i32(index: int) -> int` checks an exact nonnegative integer
index and complete scalar alignment, then reads signed little-endian i32; a
scalar may cross arbitrary generic byte-chunk boundaries.

`axiom.invocation_v2` provides frozen `InvocationLimits`, `InvocationManifest`,
and `VerifiedInvocation` records and:

```python
write_invocation(source_bytes: bytes, input_blocks: Iterable[bytes],
                 initial_output_blocks: Iterable[bytes], directory: Path,
                 *, limits: InvocationLimits) -> Path
verify_invocation(manifest: Path, *, limits: InvocationLimits) -> VerifiedInvocation
```

`InvocationLimits` contains `blobs: BlobLimits`,
`source_profile: SourceProfileV2`, and `source_limits: SourceLimitsV2`, each with
its production default. Source parser quotas may tighten but never widen C2.
The writer freshly admits source bytes before touching either buffer iterator.
The verifier freshly admits retained source bytes and compares exact source,
family, specialization, H, W, and selected profile bindings. It checks extent
arithmetic before opening any buffer blob. There is deliberately no source
value-range preflight: every valid signed-i32 input representation, including
values outside 0..1023, must reach the real source rejection path.

`InvocationManifest(source, source_sha256, family_semantics_sha256,
specialization_semantics_sha256, source_profile, H, W, input, initial_output,
buffer_contract="axiom-core-buffer-host-v1")` is immutable metadata. The three
buffer/source fields are `BlobReference` records. Its `invocation_sha256`
property computes the identity below. Caller-created records do not establish
verification authority.

`VerifiedInvocation` exposes `manifest_path`, `manifest_sha256`, `manifest`,
`limits`, `source_bytes`, `source` (the verified source blob), `source_sha256`,
`family_semantics_sha256`, `specialization_semantics_sha256`, `source_profile`,
`H`, `W`, `input`, `initial_output`, `buffer_contract`, `invocation_sha256`,
`revalidate() -> None`, and the explicit `state_v1_invocation_sha256` mapping.
Revalidation freshly verifies the complete closure and readmits source, then
compares all captured metadata and source bytes; mutation or replacement after
construction rejects. Revalidation first checks exact in-memory scalar/container
types, nested limits/references/chunks, and immutable source bytes; equality
between float/bool/int or bytearray/bytes never establishes typed authority.
The scalar reader likewise validates chunk records before offset arithmetic.
Consumers must invoke revalidation at their own trust boundary.

## Exact byte-blob schema

All documents use ASCII canonical JSON: sorted keys, no whitespace, escaped
non-ASCII text, exact integers only, no floats/nonfinite values. Duplicate keys,
unknown/missing fields, and unsupported schemas reject. SHA-256 strings are
exactly 64 lowercase hexadecimal characters. Booleans are never integer counts,
extents, offsets, lengths, or versions. JSON integer magnitude is at most
2**63-1. Metadata byte, depth, and token/item limits are checked before decoding.

A blob's `blob.json` has exactly:

```json
{"byte_length":0,"chunks":[],"schema":"axiom-blob-v2","sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
```

Each nonempty `chunks` entry has exactly `offset`, `byte_length`, `path`, and
`sha256`. Offsets start at zero, ordered contiguous positive lengths cover the
exact declared length once, and paths do not repeat within a blob. Chunks need
not be scalar-aligned or all have the same size. `sha256` at the manifest root
hashes concatenated actual chunk bytes. Empty generic blobs are supported.
A blob is arbitrary bytes and is never a semantic state.

Writers produce `chunk-00000000.bin`, subsequent ordinal chunk names, and
`blob.json`. Names are exclusively created and never overwritten. A failed
write may retain an incomplete prefix with no accepted final manifest;
callers own reservation, cleanup, failure retention, and enclosing budgets.
Existing successful files are never deleted by this transport.

## Exact invocation schema

An invocation's `invocation.json` has exactly:

```text
schema = "axiom-invocation-v2"
source = blob reference
source_sha256 = exact source bytes SHA-256
family_semantics_sha256 = fresh C2 family identity
specialization_semantics_sha256 = fresh C2 specialization identity
source_profile = exact SourceProfileV2 object
H = exact positive integer
W = exact positive integer
input = blob reference
initial_output = blob reference
buffer_contract = "axiom-core-buffer-host-v1"
invocation_sha256 = identity below
```

Each embedded blob reference has exactly `path` (relative manifest path),
`manifest_sha256`, `byte_length`, and `sha256`. Paths resolve from the invocation
manifest's parent. A blob's chunk paths resolve from its own manifest parent.
`source_profile` contains exactly `profile_id`, `max_height`, `max_width`,
`max_input_cells`, `index_semantics`, and `version`, with the exact C2 supported
values. The required host contract means immutable input, exclusive mutable
initial-output/output storage, and disjoint owned live buffer ranges. A string
is not evidence that a native allocation actually satisfies that contract;
the B3/B6 host checks ownership, generation, lengths, liveness, and disjointness.
Sharing transport files does not authorize aliased runtime buffers.

The profile permits H/W in 1..8192 and P=(H+1)*(W+1) <= 8,388,608; O=H*W.
Input is exactly 4P bytes and initial output exactly 4O bytes. Python checked
integer arithmetic precedes consumption/allocation and native-size conversion.
For H=2049/W=2047, P=4,198,400 and the byte lengths are 16,793,600 / 16,777,212.
For H=W=2048, combined state bytes are 33,570,820. These historical-shape
checks are arithmetic-only and generate no historical inputs.

## Identity domains and state-v1 mapping

`invocation_sha256` hashes canonical JSON containing exactly:

```text
identity_version = "axiom-exact-source-invocation-v2"
source = {byte_length, sha256}
source_sha256
family_semantics_sha256
specialization_semantics_sha256
source_profile
H
W
input = {byte_length, sha256}
initial_output = {byte_length, sha256}
buffer_contract
```

The named values come from the invocation above. Manifest hashes, chunk layout,
paths, physical plans, runs, acquisition, and timing are absent. Equal exact
bytes rechunked or relocated have equal invocation identities. Renaming source,
comments, source policy changes, or changed dimensions change the exact-source
invocation; family equivalence cannot substitute for exact source identity.

`VerifiedInvocation.state_v1_invocation_sha256(logical_semantics_sha256=None)`
is an explicit mapping into the existing state-v1 semantic-invocation domain.
The default logical semantic digest is C2 specialization; an explicit logical
digest may be supplied when the caller intentionally maps another domain.
It hashes exactly the state-v1 canonical object:

```text
logical_semantics_sha256 = selected logical digest
shape = {H, W}
original_input_sha256 = whole input blob digest
initial_output_sha256 = whole initial-output blob digest
```

This is deliberately different from v2 exact-source invocation identity and
does not widen v1 admission, establish correspondence, or authorize a receipt.
Tests compare the production-safe mapping with research `StateMetadata`.

## Bounds, file safety, and concurrency assumptions

`BlobLimits` defaults/absolute ceilings are 1,048,576 bytes per chunk,
16,777,216 bytes per file, 16,384 files per blob closure (including its manifest),
1,048,576 metadata bytes/document, nesting depth 16, and 65,536 metadata items
(containers, keys, and values). Limits can only tighten. Aggregated unique-path
bytes and counts, campaigns, semantic/qualification stores, failure quarantine,
capture reservation, and logical-read/acquisition accounting belong to the
enclosing stores. This transport introduces no additional aggregate allowance.

All actual reads use descriptor-relative opens from the filesystem root with
NOFOLLOW on every directory/file component. Files must be regular, bounded,
and stable while read; symlinks, escape components, NULs, backslashes, absolute
relative references, FIFOs/devices, missing data, and changing read fingerprints
reject. Writers use the same safe directory traversal and exclusive final opens.
A read checks size, device/inode, modification/change timestamps before/after;
a full traversal hashes every actual file, never accepting digest declarations
alone.

The scalar reader retains at most two chunks in an LRU cache (at most 2 MiB by
default). Cache reuse safely reopens and checks device/inode/size/mtime/ctime;
a changed fingerprint forces complete chunk rereading and digest verification.
Full `revalidate` and `iter_bytes` traversal always hashes actual contents and
clears scalar caches. Temporary read/join buffers and retained metadata/source
bytes are additional bounded working memory; writer buffering is one chunk
plus immutable flush data, excluding the caller-owned iterable's current block.
No reader allocates the complete input/output blob. Full traversal performs
linear I/O; `iter_bytes` does a prevalidation traversal plus its yielded-byte
traversal. Source retention adds at most the C2 65,536-byte limit.

Files must be stable for a consuming operation; same-UID adversarial concurrent
mutation cannot be made impossible by Python metadata records, mode 0400, or
cached fingerprints. Consumers revalidate at trust boundaries, fully acquire
all required bytes and compare actual observations before semantic sharing.
This transport provides neither an OS filesystem snapshot nor hash-only state
comparison, oracle outcomes, acquisition evidence, or native qualification.
