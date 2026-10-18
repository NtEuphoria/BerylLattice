# Task 7 kernel measurement report

Status: DONE_WITH_CONCERNS (tool implemented and smoke-verified; release qualification intentionally not run).

## Owned deliverables / interface

- `tools/measure-kernel.py`: standalone Python standard-library CLI; no compiler/product imports.
- `tools/benchmarks/kernel-throughput.c`: portable POSIX C11 driver and independent direct stencil oracle.
- `axiom/tests/test_kernel_benchmark.py`: real-Clang smoke tests, no mock native execution.

CLI, from repository root:

```sh
python tools/measure-kernel.py --baseline /path/baseline.c --candidate /path/candidate.c --clang /path/clang --height H --width W --iterations N --samples S --output /new/result.json
```

The two programs must expose `int32_t beryl_kernel(const int32_t *, int32_t *)` for the same bounded stencil shape. Inputs remain 0..1023; `(H+1)*(W+1) <= 256`. Each source is copied byte-for-byte into the temporary build, compiled separately with `-O3 -std=c11 -fno-lto -Dmain=beryl_generated_main`, and linked separately with the one separately compiled timing driver using `-fno-lto`. Original generated source mains are never executed. Snapshotted source, driver, objects, executables and compiler have SHA-256 identities in JSON. Source paths, version, commands and separate driver/compile/link/build durations are retained. Temporary executables are removed after measurement.

Timed loop: mutate exactly one input cell, external non-LTO kernel call, capture its status and one rotating output cell, maintain two rolling indices. No input regeneration, full-output copy, reference evaluation, checksum calculation, Python, ctypes or process startup is timed. Capture arrays are pre-touched using volatile writes outside timing to prevent optimization deleting initialization. Driver uses `CLOCK_MONOTONIC`. A separately timed/audited first call is the one warmup call for each process, then initialized buffers are reset. Builds complete before samples; serial order alternates baseline/candidate. Each paired sample uses the same runtime seed; samples use different seeds.

Untimed audit checks all measured statuses and captured cells against the direct original stencil formula. It replays the identical changing sequence with the real kernel, compares every output cell and unchanged input on every replay call, and compares complete final timed input/output state. Unsigned deterministic checksum binds statuses, captured outputs and final full output. The driver fails before publishing a success record on mismatch. Paired seed/checksum/final-output identities are also compared in Python. JSON retains raw elapsed ns, ns/run, first-call ns, sample count, per-program median/p95/min/max/stdev, paired candidate/baseline ratios and ratio of medians. Existing output paths, including dangling symlinks, are rejected; final output creation is exclusive.

## Exact RED/GREEN and verification

All native test runs used the actual supplied LLVM 19 Clang:

```sh
cd /workspace/BerylLattice-o3-fixes/axiom
AXIOM_TEST_NATIVE_CLANG=/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang python -m unittest tests.test_kernel_benchmark -v
```

Initial RED before tool implementation: 6 tests, 4 failures, exit 1, with correct-native/audit assertions failing because `tools/measure-kernel.py` did not exist. The two argument/nonoverwrite tests initially passed trivially on the missing script; their error-message assertions were strengthened before implementation to avoid accepting that false positive. First GREEN after implementation: 6/6 passed, exit 0. Added a targeted transient-unsampled-output replay regression test: passed against the full replay implementation. Final fresh run after self-review adjustments: **7/7 passed**, exit 0, `Ran 7 tests in 2.128s`.

Additional exact commands from repository root:

```sh
/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang -O3 -std=c11 -Wall -Wextra -Werror -fno-lto -c tools/benchmarks/kernel-throughput.c -o /tmp/beryl-kernel-driver-check.o
git diff --check -- axiom/tests/test_kernel_benchmark.py tools/measure-kernel.py tools/benchmarks/kernel-throughput.c
python tools/measure-kernel.py --help
```

All exited 0. Native smoke tests compile real 1x2 kernels, run only 19 measured calls/sample and 3 samples, verify exact source hashes and paired audit observations, and reject wrong output, nonzero status, input mutation and transient unsampled output corruption. No large measurements and no full integration suite were run, per controller instructions.

## Self-review / limitations

- No public/product/compiler code or existing tests changed. Only the three assigned tool/test files are committed; this report lives in the existing ignored coordination directory.
- External separate-TU call plus changing input and consumed result captures prevents compiler hoisting; no LTO or baked source inputs. Bounds keep direct formula arithmetic within signed i32 and checksum arithmetic is unsigned.
- Timed scope includes a small fixed mutation/capture/bookkeeping cost. Tiny smoke timing is not meaningful release performance evidence. Qualification should use controller-chosen high iteration counts and at least 21 samples, quiet fixed host and original artifact/revision identities.
- Full intermediate timed outputs are not all captured; full coverage is on the identical untimed replay plus the final timed state. Generated kernels are expected to be deterministic/stateless. A malicious stateful kernel that corrupts only an unsampled intermediate timed cell and behaves differently on replay could evade that observation. `audit_scope` states exactly what was checked; coordinator notified before commit.
- Capture storage is 8 bytes per iteration per process; long runs must choose iterations suitable for host memory. Full replay doubles kernel calls outside timing and evaluates the direct oracle but does not affect reported kernel-loop ns.
- POSIX monotonic-clock platform required (Linux/macOS); no Windows timing backend. CPU/model/load, OS and Python/compiler versions are recorded. OS/compiler caches are explicitly uncontrolled. Source files should be standalone generated C; relative private include trees are not copied.
- No throughput-regression gate is claimed passed. Measurements, acceptance decision and independent review belong to the controller.

Commit: `034d769` (`Add independently audited native kernel throughput tool`).
