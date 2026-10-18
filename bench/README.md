# Cross-language benchmark suite

Measures Project Axiom against C, Rust, Node.js, NumPy and pure Python on 14
kernels. Every result is verified, logged to an append-only JSONL file and
can be summarized or compared run to run. The aim is a feedback loop: run,
read the data, change Axiom, run again, compare.

```powershell
py -3 bench/run.py                         # small + medium sizes, all languages (~5 min)
py -3 bench/summarize.py                   # Markdown report for the latest run
py -3 bench/summarize.py --compare OLD.jsonl NEW.jsonl   # regressions / gains
```

Requires Python 3.12+, and optionally `clang`, `rustc`, `node` and `numpy`
(missing tools show up as errors for that column only). Useful options:
`--sizes s,m,l`, `--patterns all`, `--kernels sq2x2,matmul`,
`--impls c,axiom`, `--label "what changed"`, `--min-ms 300` for steadier numbers.

## What Axiom can and cannot run today

Axiom's frontend currently admits exactly one program shape, the canonical
squared 2x2 stencil (`axiom_drafts/sq2x2.ax`), with at most 256 input cells.
The suite is built around that fact rather than hiding it:

- **Runs on Axiom:** `sq2x2` at the small size, plus a sweep over workspace
  caps (0 to 1024 bytes) and both objectives. The sweep shows the planner
  switching from `inline-v1` (no scratch) to `rows2-v1` (row reuse) when
  storage allows it, with every result still independently checked.
- **Target workloads:** the other 13 kernels and the larger sizes. When today's
  grammar can write the kernel, `axiom_drafts/` holds a real draft and the
  log records Axiom's actual rejection message. When it cannot, the catalog
  lists the missing language features. `summarize.py` ranks those features by
  how many cases they block, which gives a data-driven roadmap. When a kernel
  starts passing, `--compare` reports it as a **COVERAGE GAIN**.
- **Rejection latency:** `reject_range`, `reject_shape` and `reject_profile`
  time how long Axiom takes to refuse a bad request.

## Kernels

| kernel | family | sizes s / m / l (params) | Axiom today |
|---|---|---|---|
| sq2x2 | 2-D stencil | 15x15 / 255x255 / 2047x2047 | s runs; m/l exceed 256 cells |
| stencil1d3 | 1-D stencil | 254 / 65534 / 4194302 | draft rejected |
| box3x3, laplace5, conv3x3 | 2-D stencil | 14x14 / 254x254 / 2046x2046 | drafts rejected |
| life | conditional stencil | same | not expressible |
| polymap | elementwise | 256 / 65536 / 4194304 | draft rejected |
| transpose | layout | 16x16 / 256x256 / 2048x2048 | draft rejected |
| maxpool2 | conditional stencil | 8x8 / 128x128 / 1024x1024 output | not expressible |
| sum, dot, scan, hist | reduction / scan / scatter | about 256 / 65K / 4M inputs | not expressible |
| matmul | dense linear algebra | 8 / 64 / 256 | not expressible |

Definitions live in `catalog.py` (sizes, I/O counts, missing features) and
`oracle.py` (the literal reference definition of each kernel).

## How results are made trustworthy

- **Same inputs everywhere.** Each language generates input `i` from the index
  alone (`hash`, `ramp`, `alt`, `zeros`, `max`; all values are 0..1023).
- **Independent verification.** `oracle.py` is a deliberately literal,
  NumPy-free definition. Each implementation reports its output count and a
  positional checksum (`sum((v mod p) * (i mod 65521 + 1)) mod p`,
  p = 1e9+7). Any disagreement is logged as `mismatch` and the run exits 1.
- **Timer resolution.** Implementations calibrate how many calls go into one
  sample (`inner`) so each sample spans at least 1 ms, then report per-call
  min and median. One untimed warm-up always runs first.
- **Compile time is not runtime.** Native builds are logged as `build` records.
- **Nothing is bypassed.** If the OS refuses to launch a fresh executable
  (Windows Application Control did this once in the first run), the case is
  logged as `blocked`. The suite never retries with modified binaries.

## What the Axiom number means

Axiom runs as the full checked pipeline on the local interpreter backend
(`checked-plan-interpreter-v1`): parse, admit, select (generate and
independently check every candidate plan), execute, independent reference
evaluation, comparison. `ns_median` is the **execute phase only**, the
closest analogue to a baseline's kernel time. `phases_ns_median` and
`pipeline_ns_median` keep the rest visible. The fair language comparison for
this backend is pure Python. The native C and WebAssembly backends live on
another branch (`5c14386`) and can be added as further implementations.

## Implementation protocol

Every implementation is a process taking
`kernel pattern a b min_ms max_reps` and printing one JSON line:

```json
{"impl": "c", "kernel": "sq2x2", "status": "ok", "n_out": 225, "checksum": 156208919,
 "reps": 15, "inner": 4096, "ns_min": 470, "ns_median": 480, "ns_total": 30000000}
```

`status` is `ok` or `unsupported`. To add a language (Go, Zig, Julia, Core
`.be`...), implement the 14 kernels behind that protocol and add the command
to `commands()` in `run.py`.

## Log format

`bench/results/<UTC time>-<revision>.jsonl` is append-only and flushed per
line, so a stopped run keeps its partial data.

- `type: run`: git revision, branch, dirty flag, platform, toolchain
  versions, flags, settings, SHA-256 of every benchmark source.
- `type: build`: compiler command, success and seconds.
- `type: result`: kernel, family, tier (`s`/`m`/`l`/`sweep`/`reject`),
  `a`, `b`, pattern, impl, status (`ok`, `mismatch`, `unsupported`,
  `rejected`, `skipped`, `blocked`, `error`, `timeout`), timings, `wall_ms`
  (whole process), the expected checksum, plus Axiom's `plan`, `phases_ns_median`
  and `diagnostic` where relevant.

Pure Python is skipped above `--python-max-inputs` (default 1.1M cells) so the
`l` tier finishes in reasonable time. Skips are logged.

## Scope and caveats

These are single-machine observations. Small-size numbers are dominated by
call overhead, and medians on a busy laptop vary by roughly 10 to 30 percent
between runs, so use `--compare` on the same machine and treat changes under
`--threshold` (default 10%) as noise. This is not a ranking of languages, and
the Axiom figures describe this interpreter backend at the logged revision,
not the language's ceiling.