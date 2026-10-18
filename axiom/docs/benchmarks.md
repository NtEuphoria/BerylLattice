# Local performance audit

The published [Performance lab](https://nteuphoria.github.io/beryl-playground/benchmarks.html)
can run three audited browser workloads, supports cancellation, and shows saved
native comparisons separately. Browser and native process times have different
boundaries and must be interpreted separately. Saved reports are reviewed
snapshots; running a local command does not replace or publish them.

## Precompiled native comparison

```powershell
py -3 tools/compare-playground.py --output .local/comparison.json
```

Requires `clang` and `rustc` on PATH, or use `--cc` and `--rustc` to select them.
Windows GNU Rust can use `--rust-self-contained` when its bundled linker
libraries are needed. Both generated beryl C and the direct C baseline use
`-O3 -std=c11`; Rust uses `-O`. The direct baseline sources in
`tools/benchmarks/` are unchanged. All executables, including beryl's three
shape-specific programs, are compiled before the first warm-up. Executables
are temporary and removed.

Six workloads cover three sizes and two input patterns. Each backend runs one
warm-up and five measured subprocesses, with rotating order (`--samples`
accepts 1 through 30). Ramp and checkerboard values change between iterations,
stay within 0 through 1023, and are identical for all three programs in an
iteration. Every warm-up and measured output is checked against an independent
direct formula after timing. A mismatch stops the command without a report.
Each beryl program lowers a selected, freshly checked zero-scratch physical
plan; inputs are supplied at runtime. It is compiled once per shape and reused
for both input patterns. C and Rust calculate the stencil directly and accept
bounded dimensions at runtime.

The primary measured interval includes fresh process startup, identical text
input transfer and decoding, preflight, computation, JSON output and stdout
transfer. JSON decoding and the external correctness audit happen after the
clock stops. These are process-latency observations; small measurements are
dominated by startup and do not establish kernel throughput or a language
ranking. Shape specialization and the programs' different parsers also affect
the observations. Reports record each beryl-to-baseline median ratio and whether
the observed latency meets the 2x target for both baselines. The target is not
a guarantee, and a failed target remains visible in the report.

Source admission and checked selection, fresh checking and C emission, and
native compilation have separate durations. Reports retain exact source and
generated C, source/plan/generated-C/binary/request SHA-256 identities, raw
samples, compiler commands and flags, compiler/Python versions and executable
hashes, CPU information, runner/compiler module hashes, and Git provenance.
Temporary compiler output paths identify the commands that actually ran; the
files are removed afterward. Output paths are never overwritten.

To reproduce the compiler pipeline from a reviewed public compiler ZIP, add
`--compiler-archive path/to/beryl-compiler.zip`. This loads its `beryl` modules
and records the archive hash and the `beryl/...` module hashes. Generated C is
included in each shape's compilation record for independent review.

The older Python service cost remains available explicitly:

```powershell
py -3 tools/compare-playground.py --include-python --output .local/comparison-with-python.json
```

Each case then has a separate `python_full_request` result, described in
`optional_scopes`. It includes fresh Python startup, source parsing, checked
selection, fresh checking, interpreted execution, independent source evaluation
and a richer JSON response. The primary `measurements.beryl`, `C`, and `Rust`
fields still refer to precompiled native programs. Archive mode also runs this
optional service from the selected public ZIP. This scope is distinct from
both native process latency and the warm in-process audit below.

## In-process beryl audit

From the repository root, with Python 3.12 or newer:

```powershell
py -3 tools/benchmark-playground.py --output .local/benchmark.json
```

The command runs 12 cases: 1x1, 5x7 and 15x15 output grids; increasing
and checkerboard inputs; and zero or 128 bytes of permitted plan storage.
Each case has one warm-up and three timed samples (`--repeats` changes that
count). Every run verifies the input pattern and every output against a direct
stencil calculation, in addition to the runtime's existing reference comparison.
Any mismatch stops the audit with a nonzero exit code.

Timings include parsing, plan selection, checking, interpreted execution and
the service's reference comparison. The additional benchmark audit is outside
the timed interval. These are warm, in-process measurements, not native code,
browser, HTTP, cold startup or terminal-rendering benchmarks. Output cells per
second includes all that checking overhead; it is not an unchecked loop rate.

The JSON report contains raw samples, minimum/median/maximum times, selected
plans, correctness status, Python/platform details, Git revision and whether
the working tree was dirty. Reports are local and not included in public builds.
Existing report files are never overwritten. Compare repeated runs on the same
machine with other busy applications closed; there are no machine-dependent
speed thresholds in unit tests. This is an observation, not a performance
guarantee or a complete security audit.

## Optional 20-million-number output baseline

```powershell
py -3 tools/benchmark-playground.py --io-numbers 20000000 --output .local/benchmark-20m.json
```

This writes integers 0 through 19,999,999, one per line, in bounded chunks to
a temporary file (168,888,890 bytes, about 161 MiB). Timing includes formatting,
writing, flushing and `fsync`. A separate pass verifies every line and count;
the file is then deleted. Temporary disk space is required. Filesystem caching,
antivirus and storage hardware affect results, even with `fsync`.

**This baseline is Python file output, not beryl execution.** The current
language profile allows at most 256 input cells per computation. It cannot
produce 20 million numbers in one program. This option does not bypass those
limits or claim that repeated small cases establish large-program scalability.
It avoids flooding the terminal with millions of lines.

Run the benchmark's regression tests from `axiom/`:

```powershell
$env:PYTHONPATH = 'src'
py -3 -m unittest tests.test_playground_benchmark -v
```
