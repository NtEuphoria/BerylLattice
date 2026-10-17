# Axiom complete semantic state v1

This format preserves every post-call input and output i32 byte. It validates
artifact encoding and comparison. It does not establish native acquisition,
execution correctness, runtime resources, or performance eligibility.

## Public Python API

`state_artifacts.py` uses only the Python 3.12 standard library and imports no
compiler, generator, planner, evaluator, or arbitrary commands.

- `StateMetadata(logical_semantics_sha256, H, W, original_input_sha256,
  initial_output_sha256, status="success", first_bad_index=None)`.
- `write_state(input_after, output, metadata, directory, *, limits=ArtifactLimits())`
  consumes scalar iterables, returns the absolute `directory/state.json` path,
  and verifies the resulting closure. Existing artifact paths are immutable:
  an identical byte sequence may be reused; a different one is rejected.
- `verify_state(manifest, limits=ArtifactLimits(), *, sidecars=(), closure_paths=())`
  returns `VerifiedState`; `ValidatedState` aliases that class. Extra paths are
  normalized POSIX paths relative to the state manifest directory.
- `compare_state(a, b)` revalidates both closures and compares actual scalar
  bytes, including post-call input. Metadata mismatch fails comparison. A byte
  mismatch reports `role`, scalar `index`, row/column `coordinate`, `left`, and
  `right`; successful comparison traverses all state bytes.
- `VerifiedState.iter_bytes(role)` yields bounded byte blocks in logical order;
  `iter_scalars(role)` yields signed integers. Both validate the stored closure
  identities again and rehash each chunk before exposing its bytes. Mutable
  artifact replacement, stale identity, and symlinks raise `ValueError`.
- `AcquisitionMetadata`, `write_acquisition`, and `verify_acquisition` operate on
  separate per-run declarations described below.
- `canonical_json(value)` and `read_manifest(path, limits=ArtifactLimits())` are
  shared strict JSON utilities. The latter reads one file; it does not discover
  or budget arbitrary indirect references in other protocols.

All product checks use explicit exceptions and remain active with `python -O`.

## Canonical JSON and identities

All JSON is ASCII, with sorted object keys, separators `,` and `:`, no other
whitespace and no final newline. Non-ASCII characters use JSON escapes. JSON
keys are unique. Floating/nonfinite numbers are forbidden. Decoded integer
magnitudes are at most `2**63-1`; booleans never substitute for numeric fields.
Exact field sets are required at each schema level. SHA-256 identifiers are
64 lowercase hexadecimal characters and identify exact bytes unless otherwise
specified. JSON readers bound bytes, nesting and container/token growth before
unbounded decoding; decoded item counts are checked as well.

The manifest has exactly these fields:

```json
{"chunks":[],"metadata":{"first_bad_index":null,"initial_output_sha256":"<sha256>","invocation_sha256":"<sha256>","logical_semantics_sha256":"<sha256>","original_input_sha256":"<sha256>","shape":{"H":1,"W":1},"status":"success"},"schema":"axiom-state-v1"}
```

The empty `chunks` above illustrates the schema only; it is invalid coverage.
`H` and `W` are positive output dimensions. Input shape is explicitly determined
as `(H+1,W+1)`; output shape is `(H,W)`. Both are row-major. The logical semantics
identifier names the declared equation/boundary contract, independently of its
physical plan or emitted code. Original input and initial output identifiers
name the complete pre-call row-major little-endian i32 byte sequences.

The semantic invocation identifier is the SHA-256 of canonical JSON containing
exactly `logical_semantics_sha256`, `shape` (`H`, `W`),
`original_input_sha256`, and `initial_output_sha256`. It identifies one semantic
input situation, not one physical measurement run. It excludes status/result,
plan, binary, timestamps, collector and machine paths. The verifier recomputes
this identifier. Two runs with the same complete state and default chunking
produce byte-identical semantic manifests regardless of plan or emitted kernel.

Status is exactly `success` or `input_precondition_failed`. Success requires
`first_bad_index=null`; failure requires a nonboolean integer in
`0..((H+1)*(W+1)-1)`. That index addresses original input in row-major order, with
coordinate `divmod(index,W+1)`. The format checks this relationship but does not
infer the true first invalid input or prove output preservation from the declared
pre-call hashes alone. Those require actual original data and an independent
semantic oracle/collector comparison.

## Chunk coverage and streaming encoding

Each chunk record has exactly `role`, `offset`, `byte_length`, `sha256`, `path`.
`role` is `input_after` or `output`. `offset` is a byte offset within that role;
`byte_length` is positive, divisible by four, and at most the configured chunk
bound. The v1 default is 1,048,576 bytes. Scalars use signed little-endian i32;
all values from -2,147,483,648 through 2,147,483,647 are encodable. The source
input-range contract is a separate semantic condition.

All input chunks appear first, followed by all output chunks. Each role starts
at byte offset zero and covers exactly its full shape-derived byte length,
contiguously with no overlap, gap, missing role, extra record or reordered
coverage. Distinct logical offsets may refer to the same chunk path/hash when
the actual byte content is equal. Equal content does not excuse duplicate
logical offsets or incomplete coverage. Writers use `chunks/<sha256>.i32`;
verifiers permit any safe relative file path with correct actual bytes/hash.
There is no compression, implicit fill, sparse reconstruction or checksum-only
representation in v1. Verification reads every referenced byte; comparison
traverses all reconstructed bytes even when repeated chunks share storage.

## Limits and complete closure accounting

`ArtifactLimits` defaults are:

| Field | Default |
| --- | ---: |
| `chunk_bytes` | 1,048,576 |
| `max_file_bytes` | 16,777,216 |
| `max_aggregate_bytes` | 268,435,456 |
| `max_files` | 16,384 |
| `max_logical_bytes` | 268,435,456 |
| `max_metadata_bytes` | 1,048,576 |
| `max_metadata_depth` | 16 |
| `max_metadata_items` | 65,536 |

The manifest and every chunk are included. Explicit acquisition `sidecars` and
additional `closure_paths` (such as pilot/freeze/measurement artifacts) share
this same budget. A path repeated in references counts once; equal bytes at two
different normalized paths count twice, including hard-linked files. Symlinks,
absolute references, `..`, `.`, empty path segments and backslashes are rejected.
Read and write directory components are opened individually without following
symlinks. Immutable files are created relative to pinned parent descriptors with
`O_EXCL | O_NOFOLLOW`; missing bundle/chunk directories are created with
descriptor-relative `mkdir`. Replacing an ancestor with a symlink during either
operation cannot redirect creation into its destination.

`VerifiedState.closure` retains a tuple of `ClosureFile(path, resolved_path,
sha256, byte_length)` for every budgeted path. `manifest_sha256`, `metadata`,
`chunks` and `logical_bytes` are retained separately. A later enclosing artifact
protocol must discover all its direct and indirect references and supply the
complete closure, unioning by resolved path across states and receipts. Arbitrary
JSON passed through `closure_paths` is budgeted as a file, not interpreted as a
new reference schema. This API cannot infer undisclosed dependencies.

The independent expanded bound checks `4*((H+1)*(W+1)+H*W)` before consuming or
allocating full state. Repeated-content paths cannot evade it. Writers also
check metadata envelopes before consuming state and retain only a bounded chunk
buffer, plus bounded chunk records. Metadata and aggregate limits apply even
when raw chunks individually fit the per-file limit.

## Acquisition declarations and trust boundary

The sidecar has exactly `schema="axiom-acquisition-v1"`, `state_manifest`
(the manifest filename in the same root), `state_manifest_sha256`,
`invocation_sha256`, and `acquisition`. The latter has exactly:

- `run_sha256`, `collector_sha256`, `plan_sha256`, `emitted_kernel_sha256`,
  `binary_sha256` (all SHA-256 identities);
- `mode`, either `synthetic` or `native_observed`;
- `started_utc` and `completed_utc` (UTC ISO timestamps with seconds and `Z`,
  optional 1–6 fractional digits), with completion no earlier than start.

`write_acquisition(manifest, metadata, *, name="acquisition.json", limits=...)`
creates one immutable declaration; distinct runs should choose distinct names.
`verify_state(..., sidecars=[...])` validates declarations and budgets them with
state. `verify_acquisition(path, state)` revalidates the previous full closure,
adds/budgets that sidecar, and returns its `AcquisitionMetadata`. Sidecar content
is intentionally absent from the canonical semantic manifest.

A string `native_observed` is a declaration, never proof. The format writer
cannot tell whether supplied values came from post-call memory, pre-call input,
a reference computation or fabricated data. A future native collector must bind
actual dump paths and their full bytes to the completed invocation, record its
per-run observation/comparison receipt, independently compare all post-call
input with original input, compare status/first failure and full output with an
independent oracle, and only then admit a measurement. Synthetic fixtures must
retain synthetic provenance throughout that workflow. Expected and observed
states may share immutable blobs only after actual per-invocation acquisition
and bytewise comparison. This format alone enables no native collection.

## Primary-size format validation

The synthetic test uses `(W,H)=(2047,2049)` and writes distinct input/output
chunk contents, then verifies every byte and traverses every scalar. The raw
input occupies 16,793,600 bytes, output 16,777,212 bytes, total 33,570,812 bytes
before metadata. No file exceeds the configured per-file limit. This is solely
artifact-format validation: it uses neither the seed-65537 workload nor a real
native kernel, and supplies no runtime or resource evidence.
