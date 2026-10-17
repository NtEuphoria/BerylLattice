# Axiom Core bridge

## Task 1: Explicit Core toolchain qualification

`axiom.core_toolchain` selects Core commit
`0a678b4ae6d41190c4f5a8bf063caba05759d20d` and an explicit Clang path. It
never searches for an alternative Clang or changes Core source, global
alternatives, or Core scripts. Current Core IR source declares schema 5; the
historical experimental schema 4 helper instructions are not this protocol.

```python
from pathlib import Path
from axiom.core_toolchain import inspect_toolchain, prepare_snapshot, build_core

source = Path('/workspace/beryl')
clang = Path('/workspace/scratch/axiom-toolchain-setup/toolchain/usr/lib/llvm-19/bin/clang')
preflight = inspect_toolchain(source, clang)
if not preflight.available:
    raise RuntimeError(preflight.reason)
snapshot = prepare_snapshot(source, Path('/workspace/scratch/my-core-snapshot'))
toolchain = build_core(snapshot, clang, Path('/workspace/scratch/my-core-receipts'))
toolchain.revalidate_identity()  # required before using a retained toolchain
```

Both destination directories must be new. `prepare_snapshot` verifies clean
Git state, exact commit, every tracked file's actual bytes against the pinned
Git object, and executable modes. It copies only that inventory outside the
checkout and writes a source-origin marker. `build_core` independently checks
the marker against the original clean repository and current snapshot bytes;
a supplied success record cannot substitute for those checks. The marker is
JSON data and is never executed. Snapshot inventories before/after builds
include source bytes and modes; only `src/back/runtime_embed.h` may change as
expected regeneration, and any such change is recorded separately.

Preflight records the selected Clang binary/configuration bytes and version,
then actually compiles and runs a C11 witness. The build puts a private
recording `clang` adapter in PATH that execs the exact selected executable and invokes the pinned `bash scripts/build.sh --debug`
and `bash scripts/test.sh` scripts. Arguments are passed as lists, including
paths with spaces. Build, unit, preflight and native receipts preserve exact
argv, working directory, return code, stdout, stderr and timeout/error status.
The private adapter also records actual nested build/unit Clang argument vectors
to `clang-invocations.jsonl` immediately before execution, including failed
compilations. `Toolchain.clang_invocations` retains those observed token lists,
stage, cwd and selected executable hash; these are not reconstructed from scripts.
The outer build/unit receipts retain process outcomes; invocation records do not
claim a separately observed child exit status. Capture code and log bytes are
bound as retained artifacts.
A Core witness then exercises ordinary frontend admission, AST native run,
LLVM IR, assembly and driver-job capture with `--save-native-evidence`.
Artifact bytes/hashes and Core-reported capture statuses are checked.

`Toolchain` contains absolute `compiler`/`clang` paths, binary SHA256 values,
`clang_config` and observed `clang_components` identities, `source_pin`, `source_inventory_sha256`, version
stdout, `build_receipt`, `unit_receipt`, `native_receipt`, `native_artifacts`,
and the persisted JSON `receipt_path`. `FileIdentity.lookup_path` optionally retains a lexical lookup path alongside
the resolved `path`, hash and size, so known dependency symlink retargeting is
rejected even when the previous target remains intact. `revalidate_identity()`
checks current lookup resolution and retained binary/configuration/component
bytes, both source inventories and qualification/capture artifacts.
No metadata-loading API grants permission to execute arbitrary receipt argv.
Missing or failed Clang capabilities produce unavailable preflight results;
invalid sources produce errors. Build failures raise `ToolchainError` carrying
partial command receipts and never write a successful `toolchain.json`.

The pinned Core unit suite has a confirmed existing defect: two failed checks
out of 10814 across 583 cases in `IR: initialized SET destination remains
readable during later scalar capture`. That fixture expects `replace(set n,n)`
to succeed while pinned ownership admission rejects it with BE0401. The adapter
allows exactly that named, counted failure pattern and records
`unit_status='known_pinned_baseline_failure'`, preserving exit 1 and complete
diagnostics. Every other suite failure blocks qualification. This permission
does not establish Axiom conformance; each Axiom lane needs independent checks.

The current selected Debian Clang 19.1.7 installation lives outside the system
package database. Its adjacent `clang.cfg` contains exactly `-lm\n` (four
bytes), SHA256
`bc3624e157ba6656818d5f16c70efcd0c5414ffc8f354dce80aa76d639f9587f`, to
supply the Linux math library omitted by the pinned build scripts. The adapter
binds candidate configuration files and checks the real driver's reported
loaded configuration paths. The package installation source, authenticated
package hashes, known loaded libraries and initial setup evidence are retained
under `/workspace/scratch/axiom-toolchain-setup`. Selected executable/configuration
identity does not fingerprint all transitive SDK, linker and dynamic library
dependencies. Core's path-sensitive loaded-source fingerprints remain distinct
from binary byte hashes.

Run the portable failure tests with:

```sh
cd /workspace/BerylLattice/axiom
PYTHONPATH=src python -m unittest tests.test_core_toolchain -v
```

To include actual C11/native qualification and isolated build tests:

```sh
AXIOM_TEST_CORE=/workspace/beryl \
AXIOM_TEST_CLANG=/workspace/scratch/axiom-toolchain-setup/toolchain/usr/lib/llvm-19/bin/clang \
PYTHONPATH=src python -m unittest tests.test_core_toolchain -v
```

## Checked witness and correspondence commands

Run commands from `axiom/` with `PYTHONPATH=src`. A witness selects one exact
saved plan and one explicit fixed case. `--core` is the clean pinned **source
checkout**, rather than an arbitrary compiler executable. The command performs
preflight, copies that checkout into a fresh isolated working capsule, builds
and qualifies Core there, and invokes the ordinary complete Core frontend.
The selected Clang executable is required explicitly, including paths with
spaces. Core's pinned unit baseline exception remains visible in its receipt.

```sh
PYTHONPATH=src python -m axiom witness source.ax \
  --plan plan.json --case case.json \
  --core /workspace/beryl \
  --clang /workspace/scratch/axiom-toolchain-setup/toolchain/usr/lib/llvm-19/bin/clang \
  --out /workspace/scratch/my-witness-capsule
```

The default witness lane is production AST differential execution. Optional
`--lane reference`, `--lane ast`, or `--lane ir` chooses the lane explicitly;
`--release` requests Core's release mode. An unsupported fixed plan retains
its own failure and diagnostics. The command never substitutes another plan.
A general `compile` command remains deferred until a runtime entry contract
exists: `kernel.be` and `witness.be` are distinct source artifacts, and the
latter embeds one case and observation entry point.

`case.json` must contain exactly these three fields. Array lengths must match
the admitted shape: `(H+1)*(W+1)` input cells and `H*W` initialized output cells.
Every scalar must be an exact signed i32 JSON integer; booleans are rejected.
Values outside the source input precondition are useful cases: execution must
return the first invalid input index and preserve every output sentinel.

```json
{"schema_version":1,"input":[0,1,2,3],"initial_output":[-99]}
```

That example requires H=1/W=1 source. H=5/W=7 requires 48 input cells and 35
output cells. Source and saved plan bytes are freshly decoded and checked
before emission. The case's canonical SHA-256 binds the invocation; original
case bytes and their separate exact-byte hash are retained as well. Emission
records bind exact source/plan/kernel/witness bytes, emitter version and code
digest, complete source mappings, and scalar observation layout.

A conformance campaign consumes an explicit self-contained source/case manifest
and an existing qualified toolchain receipt:

```sh
PYTHONPATH=src python -m axiom conformance \
  --manifest quick-manifest.json \
  --toolchain '/workspace/scratch/axiom-toolchain-task1-review1/output with spaces/toolchain.json' \
  --out /workspace/scratch/my-correspondence-capsule --workers 4
```

The accepted manifest v1 is documented in
[`tests/integration/case-schema.json`](../tests/integration/case-schema.json).
It contains `schema_version`, `artifact_kind="core_correspondence_manifest"`,
explicit distinct `plans` (`inline-v1`, `materialize-v1`, `rows2-v1`), explicit
`lanes` objects (`lane`, `release`), and `cases`. Each case supplies `case_id`,
`pattern`, `shape`, exact `source_utf8`, its `source_sha256`, `input`, and
`initial_output`. Unknown fields, duplicate cases/lanes/plans, wrong shapes,
changed source bytes, and invalid scalar types are rejected. Production reads
those explicit sources; it imports no integration test modules or generators.
The bounded consumer accepts at most 512 cases and an 8 MiB manifest.

`load_toolchain(receipt)` strictly decodes existing records and revalidates the
pinned source inventory, built snapshot, compiler and Clang binaries, known
configuration and component identities, actual build/unit invocation capture,
and retained native qualification evidence. It executes no receipt argv.
An exported receipt copy is accepted only while the recorded original receipt
still exists with identical bytes. Missing or changed underlying runtime files
cannot be repaired by rewriting receipt paths.

Campaigns use one to four workers (`--workers`, default 4). Bundle construction
and independent source evaluation precede execution; each invocation owns a
fresh job directory and the fixed 120000 ms Core stage budget plus independent
1200000 ms whole-pipeline budget. Interruption cancels queued cells and joins
active supervisors before returning. Complete rows are sorted by case, plan,
lane and release mode for the final matrix. Partial runs retain private
diagnostics and cannot produce an accepted completion manifest.

## Observations, publication, and trusted base

A successful Core report is one dimension. The coordinator separately decodes
status, **every input cell**, and **every output cell** from both Core reference
and native streams when present, and compares each with `evaluate_source` on
the original Axiom source. The source oracle does not consume physical plans
or generated Core source. Agreement between Core lanes therefore cannot hide
a common emitter error. Invalid input returns the exact first failing index;
valid input returns -1. Core event offsets across different generated programs
are not compared as identical Axiom events.

`lane-matrix.json` records `source_emission`, `build_status`,
`conformance_status`, complete expected/observed tuples, per-field comparisons,
and the runner's full argv, executable identities, timeout/cleanup outcomes,
job/result paths, and retained artifact hashes. Unavailable, timeout, compiler
error, infrastructure error, and semantic mismatch remain distinct results.
Exit categories preserve Plan01: 0 successful correspondence, 2 invalid input,
3 unsupported source/protocol, 4 no eligible fixed plan, 5 infrastructure or
unavailable execution, and 6 semantic mismatch. An input-precondition rejection
that exactly matches the source oracle is successful correspondence.

Execution/build files live in a fresh retained private working directory named
`/tmp/axiom-core-capsule-*`; the final JSON response identifies it. `--out` is an
inspectable export. Publication pins each real output directory component with
`O_NOFOLLOW` and writes through directory descriptors. It verifies every copied
file and its hash before publishing the immutable `manifest.json` last. A
symlinked or changed output ancestor cannot redirect compiler or export writes.
An existing manifest is never replaced. Each exported file records its relative
export path and absolute original path; external retained toolchain references
also list exact paths, resolved targets, byte sizes and hashes. The complete
retained qualification closure includes the fixed witness, every process
stdout/stderr log, argv files, generated C/runtime files and native outputs.
Their baseline hashes are captured before case execution and rechecked before
publication. Transient C11 preflight probe paths are historical receipt data;
those deleted temporary files are explicitly outside the retained closure.

Keep the original private working directory and external toolchain files when
reusing receipts. Exported metadata retains those absolute paths, so this is an
inspectable reproducibility capsule with explicit original/copy mappings, not
a promise that moving the export relocates a qualified compiler. Repeated
witness emission from identical source/plan/case bytes should reproduce source
and mapping identities. Native executable bytes can vary with build paths and
build IDs; their hashes identify artifacts and do not prove behavior.

The trusted base includes source admission/evaluation, finite-plan checking,
source emission/mapping, strict observation/receipt decoding, subprocess and
filesystem isolation, pinned Core admission/lowering, selected Clang, and the
observed runtime dependencies. Clang configuration and known component bytes
are checked, but transitive SDK/linker/library identity remains incomplete.
IR retains its 256-cell aggregate and 64 KiB declared-storage bounds. These
commands establish empirical correspondence for explicit tested cases; they
make no universal compiled-input proof, new native ABI, runtime memory-bound,
throughput, or large-shape claim.
