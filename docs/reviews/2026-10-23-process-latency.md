# Process latency: a faster standalone driver (2026-10-23)

## Question

The playground's `benchmark-results.json` showed beryl slower than C in 5 of 6 cases: Linux, clang
19.1.7, 21 samples, median whole-process time of about 0.8 ms. Why, and can beryl lead?

## Cause

The harness (`tools/compare-playground.py`) times whole processes. Each one runs:

1. process startup;
2. text input decoding;
3. the input preflight;
4. the kernel;
5. JSON output.

The kernel takes nanoseconds. What remains is mostly fixed process cost plus I/O.

beryl's standalone driver read each number with three or four stdio calls (`fgetc`, `ungetc`,
`scanf("%63s%n")`, `fgetc`) and `strtoll`, to enforce strict token rules. It printed with
`printf` per value. The C baseline makes one `scanf("%d")` per value. Rust reads stdin once.

## Change

`native_codegen._FAST_DRIVER` keeps the same token rules and exit codes, and changes only the I/O:

- **one bulk read** of standard input;
- **a strict hand-written parser**: tokens of at most 63 bytes, an optional sign then digits only,
  values within i32, exact counts, nothing after the last value, NUL rejected;
- **buffered output** through one `fwrite`.

Compact, window, reduce-v1 and scale-v1 artifacts use it. The canonical finite emitter keeps the
original `_DRIVER`, because its bytes are published and pinned by
`test_public_finite_bytes_remain_stable_for_all_schedules`.

**Verified behavior.** The binary builds cleanly with `-Wall -Wextra -Werror`. On good input it
matches the reference evaluator, still accepting leading `+` signs and mixed whitespace (`\t`,
`\r\n`). It rejects all 23 malformed payloads from both driver tests with no output, and still
accepts a 63-byte token.

## Results

**Linux** (WSL2 Ubuntu, kernel 6.6, gcc -O3 for every binary). This is the website's six cases,
300 interleaved launches each, with every output audited against the direct formula. Median ms:

| case | beryl (fast) | beryl (old) | C | fast / C | old / C |
|---|---|---|---|---|---|
| 1x1 ramp | 0.9662 | 0.9995 | 0.9839 | 0.982 | 1.016 |
| 1x1 checkerboard | 1.1902 | 1.2414 | 1.2432 | 0.957 | 0.999 |
| 5x7 ramp | 1.1406 | 1.1828 | 1.1801 | 0.967 | 1.002 |
| 5x7 checkerboard | 1.0924 | 1.0919 | 1.1165 | 0.978 | 0.978 |
| 15x15 ramp | 1.0491 | 1.1084 | 1.0908 | 0.962 | 1.016 |
| 15x15 checkerboard | 1.0001 | 1.0524 | 1.0468 | 0.955 | 1.005 |

The fast driver leads C in 6 of 6 cases (geometric mean 0.967). The old driver ties C (1.003),
which reproduces the published deficit. Rust is not installed in this WSL image; the published
Linux run had Rust slower than C in every case.

**Windows 11** (clang 22.1.6, rustc 1.96 with `link-self-contained`). Launch overhead is about
10 ms here, so differences are close to noise.

| binary | median ms (15x15, 200 launches) | executable |
|---|---|---|
| beryl, fast driver | 9.999 | 92 KB |
| beryl, old driver | 10.056 | 96 KB |
| C | 10.005 | 93 KB |
| Rust | 10.762 | 4.8 MB |

The harness itself (21 samples, `.local/proc-bench/fast-driver-1.json`) gives a geometric mean of
1.003 against C, with 2 of 6 wins: within launch noise on this OS.

## Still to do

- Regenerate `axiom/src/axiom/playground_web/benchmark-results.json` on the reference Linux host
  (clang 19.1.7, rustc 1.99.1) with the harness, so the published table reflects this driver.
- These measurements are process latency, not kernel speed; the page should say so. For kernel
  speed, see the kernel-only benchmarks in `bench/`.
