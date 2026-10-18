# Local performance audit

The published [Performance lab](https://nteuphoria.github.io/beryl-playground/benchmarks.html)
can run three audited browser workloads, supports cancellation, and shows saved
Windows C/Rust comparisons separately. Browser runs use one warm-up and three
samples per size, with a two-minute overall limit.

## C and Rust comparison

```powershell
py -3 tools/compare-playground.py --output .local/comparison.json
```

Requires `clang` and `rustc` on PATH, or use `--cc` and `--rustc` to select them.
Windows GNU Rust can use `--rust-self-contained` when its bundled linker
libraries are needed. C uses `-O3 -std=c11`; Rust uses `-O`. Native compilation
is outside the measured interval. Executables are temporary and removed.

Six workloads cover three sizes and two input patterns. Each backend runs one
warm-up and five measured subprocesses, with rotating order. All receive the
same values, and every output is compared with a direct formula. beryl uses a
zero-scratch plan; C and Rust calculate the stencil directly. Native sources
are in `tools/benchmarks/` and included as downloads in the public release.

The measured interval includes process startup, input decoding and stdout
transfer. beryl also parses source, selects and freshly checks a plan and
performs its reference comparison, returning a richer report. Consequently
these are implementation/request-latency observations, not kernel-only or
equal-feature language rankings. Small native measurements are dominated by
startup. Do not compare the saved native numbers directly with browser times.
Compiler versions, flags, native source hashes and raw samples are recorded.
The published JSON is a deliberately reviewed snapshot; running the script
does not automatically replace or publish it.

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
