# Local performance audit

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
