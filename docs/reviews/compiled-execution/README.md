# Compiled bounded execution review

User goal: approach C/Rust latency in the existing stencil benchmark.
Implementation commit: `5c14386b78bbc0ddb8f589d0dca5be1a74b0e5df`.

## Native measurements

Linux, Clang 19.1.7 and isolated official Rust 1.99.1. The exact reviewed public
13-module archive is the compiler source, not a separate private emitter variant.
All three programs compile before timing. Each case has one discarded warm-up,
21 measured fresh processes and rotating execution order. Inputs change every
iteration and are identical for each implementation in that iteration. Every
output is audited against the direct formula outside the timed interval.

| Case | beryl ms | C ms | Rust ms |
| --- | ---: | ---: | ---: |
| 1×1 ramp | 0.794 | 0.744 | 0.843 |
| 1×1 checkerboard | 0.758 | 0.810 | 0.918 |
| 5×7 ramp | 0.798 | 0.834 | 0.934 |
| 5×7 checkerboard | 0.777 | 0.805 | 0.938 |
| 15×15 ramp | 0.800 | 0.789 | 0.876 |
| 15×15 checkerboard | 0.827 | 0.839 | 0.935 |

All six cases meet the within-2x target against both baselines. Beryl is within
7% of C here. These tiny process measurements are dominated by startup and I/O;
they do not establish a general language-speed ranking or scalable performance.
The beryl source has a declared fixed shape, while the direct C/Rust baselines
accept the shape at runtime. Beryl lowers the actual selected plan to C; Clang
performs the native optimization. No input values are embedded during compilation.

The public `axiom/src/axiom/playground_web/benchmark-results.json` retains raw
samples, exact source/generated C, input recipes/hashes, plan/compiler/binary/module
hashes, flags, compilation durations and the clean implementation revision.
Only absolute host/temporary path names were reduced to basenames in that public
copy. The previous Windows full-Python-request comparison is retained separately;
these new numbers are a different implementation and benchmark scope.

## Browser measurements

Chromium 154.0.8037.57, same host, alternating versions. Five measured verified
requests follow the first warm-up request, with changing data on every call.
Before: public interpreter release `cc9f115`; after: compiled Wasm backend. Runtime
startup is excluded. The first new-source request and compilation duration are
retained separately, including the first Wasm invocation's initialization cost.
Every complete observation and plan report matches after excluding backend/timing
fields; every output also passes an external formula audit.

| Case | Before ms | Prepared request ms | Original compilation ms |
| --- | ---: | ---: | ---: |
| 5×7 ramp | 89.1 | 5.8 | 118.0 |
| 15×15 ramp | 568.9 | 13.9 | 602.6 |
| 15×15 checkerboard | 553.3 | 14.2 | 602.6 |

The browser request includes scalar validation, worker transfer, generated Wasm
execution, complete observation acquisition and fresh independent source evaluation.
Compilation remains visible in run details after reuse. Cold source preparation
still takes time and can exceed the old request's latency; the gain is repeated
execution after preparation. The browser and native measurements have distinct
boundaries and must not be directly compared.

## Validation

- Full Python suite: 341 tests, no failures, 22 existing Core prerequisite skips.
  Native codegen and Wasm tests execute actual compiled code. The selection corpus
  covers all 955 supported shapes and 14,518 cap/objective contexts.
- UI/transport suite: 14 passing tests.
- Final public-package suite: 9 passing tests, including isolated ZIP import,
  actual reused Wasm execution, full independent comparison, deterministic builds,
  bounded import closure and source-branding checks.
- Chromium: main playground, report downloads, compiled reuse and visible cold
  cost, cap/input changes, precondition rejection, reset/keyboard/responsiveness,
  six native table rows and all three compiled browser benchmark workloads.
- Independent backend/service/Worker/benchmark reviews completed. Fixed the native
  exact-byte plan identity, optional Python benchmark setup and hidden cold-cost
  display findings with regression tests.

Public source is exactly 13 reviewed bounded modules plus LICENSE. Core bindings,
scalable research and recovery records are excluded. Manifest hashes and the
compiler archive hash must match the archive used for these native measurements.

## Reproduction

```sh
python3 tools/build-playground-site.py --output /tmp/beryl-compiled-site
python3 tools/compare-playground.py --cc /path/to/clang --rustc /path/to/rustc \
  --compiler-archive /tmp/beryl-compiled-site/beryl-compiler.zip \
  --samples 21 --output /tmp/beryl-native-comparison.json
```

`--include-python` additionally measures the previous complete interpreter request
scope separately. The retained browser harness accepts baseline/candidate static
site URLs and an output JSON path, using this environment's installed Playwright
and Chromium. Rust installation source and checksum provenance are retained here.
