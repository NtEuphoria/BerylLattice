# Playground serialization performance

The 225-output bounded demo repeatedly serialized operation shells while validating
plans. A profile counted 32,931 calls to the generic canonical JSON encoder in one
15×15 checkerboard request. The checker also validated each plan immediately before
its digest encoder performed the same validation again.

The fix counts the exact canonical byte size of validated operation fields, uses
one final JSON encoding after structural validation, and shares the digest
encoder's validation pass with checking. No proof cache, skipped semantic check,
new trusted input, altered plan, or changed work budget is introduced. All four
semantic checks per request remain; generic JSON calls fall to 16 and structural
validation passes from 10 to 6. Encoded bytes, digests and complete responses match.

## Measurements

Baseline private source: `58f1f31a20fafa76a909af124dff3cfbfea3c445`.
Baseline public release: `2bb913bfcdf5453a6d071d98c29ab4775db6226e`.
Source hashes and candidate release identity are retained in the JSON reports.

Both versions ran serially on the same Linux host, alternating order, with one
warm-up and five measured samples per version and case. Whole-process measurements
use CPython 3.12.14 and include startup through complete response transfer. Browser
measurements use Chromium 154.0.8037.57 and the pinned Pyodide 0.27.7 runtime,
including worker communication but excluding runtime startup. Browser cases use
cap64; the process table below uses cap0, matching the saved comparison's constraint.
Additional cap64/cap128 process samples are retained in the report.

Every response was compared exactly between versions, including plan identities,
checks, work counters and outputs. Every output was also audited against the direct
stencil formula outside the timed interval. Profiling was separate from timings;
no test suites ran concurrently with either measurement run.

| Boundary | Workload | Before | After | Ratio |
| --- | --- | ---: | ---: | ---: |
| CPython request | 1×1 ramp | 58.1 ms | 57.9 ms | 1.00× |
| CPython request | 1×1 checkerboard | 61.6 ms | 59.5 ms | 1.04× |
| CPython request | 5×7 ramp | 118.6 ms | 82.8 ms | 1.43× |
| CPython request | 5×7 checkerboard | 122.4 ms | 88.2 ms | 1.39× |
| CPython request | 15×15 ramp | 509.0 ms | 276.5 ms | 1.84× |
| CPython request | 15×15 checkerboard | 512.3 ms | 281.9 ms | 1.82× |
| Browser request | 5×7 ramp | 171.0 ms | 91.0 ms | 1.88× |
| Browser request | 15×15 ramp | 1050.9 ms | 555.6 ms | 1.89× |
| Browser request | 15×15 checkerboard | 1122.1 ms | 557.9 ms | 2.01× |

These are latency improvements for the same Python implementation and request,
not native code or C/Rust speed comparisons. The saved Windows timings were not
rerun and remain unchanged; the public page labels them as a historical baseline.
The remaining Python planning and semantic checking cost still dominates tiny
workloads. Native execution and separating compilation from repeated execution
remain separate implementation work.

## Validation

- Full Python suite: 301 tests, 22 native prerequisites/qualification skips, no failures.
  This covers all 955 supported shapes and 14,518 objective/cap contexts.
- UI unit suite: 12 tests passed.
- Real browser smoke: execution, result download, cap selection, input failures,
  reset behavior, responsive and keyboard
  behavior, with no page errors.
- Independent review: 11,865 differential codec comparisons against baseline,
  including malformed fields, hostile types, Unicode and exact byte boundaries.
- Export manifest verified: 24 files; only the archive, its manifest and the
  historical-baseline note differ. Inside the archive only checker.py and codec.py
  change. Public module allowlist, licensing and branding checks pass.

## Reproduction

Extract the baseline compiler sources from the commit above into a separate folder.
The source fixture is the same string used by the retained before-run request.

```sh
python3 docs/reviews/playground-performance/compare.py \
  --before /path/to/baseline/axiom/src \
  --after /path/to/candidate/axiom/src \
  --source docs/reviews/playground-performance/baseline-source.json \
  --output /tmp/playground-process-comparison.json
```

Serve the baseline and candidate static release folders on loopback. The retained
browser harness uses this environment's Playwright module and `/usr/bin/chromium`.

```sh
node docs/reviews/playground-performance/browser-compare.cjs \
  http://127.0.0.1:PORT/before/ http://127.0.0.1:PORT/after/ \
  /tmp/playground-browser-comparison.json
```
