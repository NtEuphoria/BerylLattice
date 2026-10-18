# Research compilation measurement

These scripts measure fresh compilation without changing public artifacts,
production functions, compiler flags, quotas or deterministic work receipts.
Run performance qualification serially on clean baseline/candidate revisions;
record the full output reports. A dirty-tree report is development evidence and
retains module hashes, but does not identify an immutable release revision.
The retained pre-change probes in `docs/reviews/fast-compilation` are diagnostic
starting evidence, not substitutes for paired current/old samples.

## Python runtime-ready preparation and native compiler

```sh
python3 tools/profile-compilation.py --repo /path/to/candidate \
  --baseline-repo /path/to/baseline --samples 21 --diagnostics \
  --output /tmp/paired-compilation.json
```

Both revisions execute in separate Python processes. Imports finish before
preparation timing; process startup is excluded. Revision order reverses each
round. Every sample retains exact source, source/plan/module identities, candidate
metadata, generated module bytes/local count, revision/module/harness hashes and
raw preparation time. An extracted Git archive can be measured directly: pass
`--baseline-revision COMMIT` (or `--repo-revision COMMIT` for a candidate archive).
Such snapshots retain `revision: null`, unknown dirty state, a separately declared
origin revision and exact module hashes. This caller-supplied annotation does not
claim that the snapshot was independently checked against Git. Archives nested
inside another checkout never inherit that parent's HEAD. `--diagnostics` adds separate first-round cProfile counts
and request-local trace reports where supported. These instrumented preparations
are outside wall samples. An absent trace field in an older compiler means no
trace API, rather than zero compiler work. The profiler does not execute Wasm;
use the browser audit below for independently checked observations.

Add `--cc /path/to/clang` for fresh source-to-native preparation. Checkouts with
`source_compilation.compile_native_source` use that actual source coordinator:
fresh admission, ranked proof, compact C emission or its typed finite fallback.
Older checkouts without the coordinator/API use their original public
admission/legacy selection followed by freshly checked public byte emission.
The report labels these `source-coordinator` and `legacy-public-bytes`; a missing
dependency inside a present coordinator is an error, rather than silent fallback.
No prior service/Wasm proof is reused for the native preparation.

`source_compilation_seconds` (and its nanosecond equivalent) covers the full fresh
frontend through returned C for either pipeline. It does not invent old
selection/emission subdivisions for the new coordinator.
`native_compiler_link_ns` separately measures the real Clang invocation on the
actual returned C. `total_fresh_native_preparation_ns`/`_seconds` measures the
whole wall interval through source preparation, C-file materialization and real
compiler/link. API resolution/imports precede this runtime-ready interval;
artifact hashing and independently audited execution follow it. These native
fields (native measurement schema version 2) are distinct from the service's Wasm
preparation samples. `native_medians_ns` summarizes each pipeline's source,
compiler/link and whole-wall medians; every raw interval remains in `rounds`.

Native source/plan/operations, actual codegen/hint identities and fallback reason,
candidate states, C bytes/hash, executable bytes/hash, toolchain binary/version
and flags are retained. With `--diagnostics`, separate native cProfile and
supported request-local trace preparations must reproduce the timed C identity.
Separate instrumented object and LLVM IR builds retain complete Clang time-trace
events and object/optimized-IR sizes and hashes. All diagnostic preparations and
extra builds are excluded from the native wall samples. Clang is required for
the native option; ordinary Python preparation does not need it.

Default flags remain `-O3 -std=c11`. An optimization experiment must pass every
flag explicitly, for example `--cflag=-O2 --cflag=-std=c11`, and report kernel
throughput separately before adopting a release policy. Compilation size alone
is not a latency result.

`--fixture-set qualification` is the four retained 1x1/5x7/15x15 cases.
`--fixture-set boundary` covers 1x1, 5x7, 15x15, 1x127, 127x1, 2x4 and 3x2;
both objectives; and caps one below, equal and one above each schedule's logical
reservation (zero is clamped at zero). Explicit comment, rename, cap, objective
and input-only edit fixtures are included. Each stays within 256 inputs.
Use `--list-fixtures` to retain the matrix and `--fixture-id ID` to select exact
cases. `--fixture-set smoke --samples 1` is a quick functional check.

## Real Chromium, cold engine or runtime-ready repeated source

Build or obtain both reviewed static sites, including their local pinned
runtime. The harness starts its own temporary loopback HTTP server, verifies
served files against local hashes, and leaves site files unchanged.

```sh
node tools/benchmarks/compilation.cjs \
  --site /path/to/candidate-site --baseline-site /path/to/baseline-site \
  --mode engine-cold --samples 21 --diagnostics \
  --output /tmp/paired-browser-compilation.json
```

The default is **21 engine-cold samples per fixture/revision**. Each sample starts
a fresh Chromium process, fresh temporary persistent profile and fresh Worker;
profile directories are removed after the browser exits. Runtime/import boot is
measured before the first user source and kept outside preparation samples.
Browser launch/page setup plus boot is retained separately too. There is no
warmup of the user program. `--mode source-fresh` keeps one browser/profile/Worker
per revision; identical Wasm may benefit from engine caches even though each
source has a fresh comment nonce. A new Worker alone would not establish cold
engine state. The report explicitly labels these scopes. Booting Pyodide itself
loads its separate runtime Wasm and is part of the runtime-ready precondition.

The same nonce-bearing source is used for both revisions of a pair. Revision
order reverses each round and fixture order rotates. Python bridge/emission,
Wasm compile, instantiate, complete fresh preparation, first execution and
verification are separate fields. All phase fields are inclusive and tiny browser
timings may round to zero. First execution includes input/output initialization,
the first exported call and complete observation snapshot; lazy engine work may
be charged there. The second call reuses the same instance with changed input.
Both complete observations must agree with the retained original-AST evaluator
and an independent formula; input preservation is checked. Timing audits and
hashing occur outside preparation. Diagnostic preparations happen afterward.

The report retains raw samples, full sources, complete observations, candidate
states, source/plan/module/compiler archive hashes, runtime/harness hashes,
served-file hashes, browser/host identity and separate boot observations. It
records actual module local declarations rather than inferring locals from plan
operation counts. The release manifest hash is retained; the harness verifies
served compiler bytes and records every runtime file actually fetched. Original
sites' reviewed archive-member/manifest audits remain the builder's responsibility.

Options `--fixture-set`, `--fixture-id`, and `--python` mirror the Python tool.
Use `--chromium PATH` and `--playwright PATH` for other installations. The default
tries `playwright-core`, then the managed environment's existing installation at
`/opt/codex/cua_node/lib/node_modules/playwright-core`; Chromium defaults to
`/usr/bin/chromium`. No npm install is needed in that environment. External CDN
runtimes are rejected so served-file identities remain locally auditable.
The research page/Worker uses the shipped local-runtime CSP capabilities. This
phase harness supplements actual product Worker/UI/CSP integration tests.

Contract checks:

```sh
cd axiom
PYTHONPATH=src python -m unittest tests.test_compilation_trace -v
cd ..
node tools/benchmarks/test-compilation.cjs
```
