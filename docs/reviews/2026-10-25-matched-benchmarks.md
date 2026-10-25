# Matched benchmarks: equal interfaces and equal thread counts

Date: 2026-10-25. Commit `b49d4ec` plus the Medici-sprint working tree (`bench/` thread
support only; no compiler changes).

Earlier speed claims compared beryl on all cores against single-threaded C and Rust. Those
baselines also store 64-bit outputs and check no inputs. These runs separate the three
differences:
- like-for-like hand C;
- equal thread counts;
- every loss listed.

## Setup

**Machine.** AMD Ryzen 3 3100: 4 cores, 8 threads, 2 MB L2, 16 MB L3. Windows 11, and WSL2
Ubuntu on the same machine.

**Toolchains.**
- Windows: clang 22.1.6 `-O3`; rustc and cargo 1.96 `opt-level=3`.
- Linux: gcc `-O3`.

**Thread counts.**
- `--threads 1` gives beryl 1 thread.
- `--threads 4` gives every parallel implementation 4 threads, the physical core count.
- Every result records its thread count. The summary shows a ratio only between equal thread
  counts, and the runner refuses parallel baselines without `--threads`.

**Baselines.**

| baseline | outputs | input checks | sizes | threads |
|---|---|---|---|---|
| hand C (6 stencil and map kernels) | 32-bit, like beryl | the same check as beryl | fixed at compile time, like beryl | 1 |
| `c`, `rust` | 64-bit | none | given at run time | 1 |
| `c-mt` (OpenMP, gcc, Linux) | 64-bit | none | given at run time | 4 |
| `rust-mt` (Rayon) | 64-bit | none | given at run time | 4 |

The plain baselines write twice as many output bytes as beryl, which favors beryl. They
check nothing, which favors them. Hand C removes both differences; it exists for 6 of the
10 kernels.

**Protocol.** The bench harness's usual one: median per call, at least 100 ms timed per
case, every output checked against the independent oracle. All 90 results are verified.

**Logs.** `.local/matched/20261025T050714Z-b49d4ec.jsonl` (run 1), `…050949Z…` (run 2) and
`…051218Z…` (run 3). Every per-case number is in the appendix below.

## Results

Ratios are beryl's speed relative to the baseline: above 1 means beryl is faster.

### Like for like: beryl against hand C, one thread each

| size | faster in | geomean |
|---|---|---|
| s | 6/6 | 1.87x |
| m | 6/6 | 1.24x |
| l | 6/6 | 1.17x |
| **all** | **18/18** | **1.39x** |

### Against the plain baselines, one thread each (run 1)

| size | wins against C | geomean against C | wins against Rust | geomean against Rust |
|---|---|---|---|---|
| s | 10/10 | 2.00x | 10/10 | 2.44x |
| m | 10/10 | 2.37x | 10/10 | 2.13x |
| l | 7/10 | 1.35x | 7/10 | 1.23x |
| all | 27/30 | 1.86x | 27/30 | 1.86x |

These are larger than the hand-C ratios partly because of the 64-bit outputs; quote them only
with that caveat.

### Four threads each

| run | size | wins | geomean |
|---|---|---|---|
| 3: C with OpenMP (Linux) | m | 9/10 | 2.00x |
| 3: C with OpenMP (Linux) | l | 8/10 | 1.17x |
| 2: Rust with Rayon (Windows) | l | 8/10 | 1.29x |

Two figures are left out of these headlines:
- **The s size, both runs.** OpenMP and Rayon wake their pools on every call, at 2–17 µs.
  beryl keeps sub-microsecond kernels single-threaded, so these ratios (20x and 133x) mostly
  measure the baselines' thread-launch overhead.
- **Rayon at the m size** (3.46x). The same overhead dominates there: four-thread Rayon was
  slower than one-thread Rust for sum (28 µs against 12.5), dot (27.9 against 13.8) and
  stencil1d3 (50.4 against 36.9).

## Every loss

| run | case | beryl | baseline | beryl's time over the baseline's |
|---|---|---|---|---|
| 1 | transpose l | 31.7 ms | C 29.1 ms, Rust 30.2 ms | 1.09x, 1.05x |
| 1 | sum l | 1.90 ms | C 1.24 ms, Rust 1.22 ms | 1.52x, 1.56x |
| 1 | dot l | 1.88 ms | C 1.34 ms, Rust 1.19 ms | 1.40x, 1.58x |
| 2 | sum l | 1.02 ms | Rayon 522 µs | 1.96x |
| 2 | dot l | 959 µs | Rayon 577 µs | 1.66x |
| 3 | sum m | 6.80 µs | OpenMP 6.50 µs | 1.05x |
| 3 | sum l | 1.16 ms | OpenMP 642 µs | 1.81x |
| 3 | dot l | 1.35 ms | OpenMP 643 µs | 2.11x |

beryl never lost to hand C.

**Likely cause (not yet measured separately).** The memory-bound losses are the cases that
read 16 MB once and do almost no arithmetic: sum, dot and transpose at the l size. beryl's
contract checks the whole input before writing any output, so it reads the input twice; the
plain baselines read it once and check nothing.

The next optimization follows from that. For a single-cell reduction the output is written
only at the end, so the check can be fused into the summing pass without weakening the
contract. If any value is out of range, the existing scan finds the first bad index and the
output stays untouched.

## What the proof covers

beryl's checker proves that each loop plan computes exactly the source's meaning, never
reads out of bounds, and cannot overflow its declared types. Some parts are argued and
tested, but not yet checked:
- the step that prints C from a proved plan;
- the exact 32-bit blocks inside 64-bit sums;
- the carry-v1 row ring;
- the split across threads.

The testing is reference agreement, mutation fuzzing and sanitizer runs.

## Claims now allowed

These may be used, word for word, in the video, the email and the website:

1. "On one thread, beryl was 1.39x faster than hand-written C with the same interface (32-bit
   outputs, the same input checks, compile-time sizes), and faster in all 18 cases measured."
2. "Against single-threaded C and Rust baselines that store 64-bit outputs and check no
   inputs, beryl won 27 of 30 benchmarks."
3. "With four threads each, beryl was 2.0x faster than C with OpenMP at in-cache sizes, and
   1.17x faster than OpenMP and 1.29x faster than Rust with Rayon at sizes too large for
   cache."
4. "beryl still loses on very large sums and dot products (1.4–2.1x slower), on a very large
   transpose on one thread (1.05–1.09x slower), and on one mid-size sum against OpenMP (1.05x
   slower)."
5. "beryl's checker proves each optimized plan is exactly the program, in bounds and free of
   overflow. Turning that plan into C, and some of its optimizations, are tested but not yet
   checked."

Not allowed:
- "faster than C", "thread for thread" or "equivalent C" without the qualifiers above;
- the s-size four-thread ratios, or the Rayon m-size ratio, as headlines;
- any statement about GPUs or AI training as a current capability.

## Appendix: every case

### Run 1: one thread each (Windows, clang)

Times are medians; the ratio in brackets is beryl (or the other baseline) divided by the first baseline in the row with the same thread count.

| kernel | size | pattern | c | rust | beryl |
|---|---|---|---|---|---|
| sq2x2 | s | hash | 377 ns | 613 ns (1.63x) | 276 ns (0.732x) |
| sq2x2 | m | hash | 111 us | 173 us (1.55x) | 61.3 us (0.55x) |
| sq2x2 | l | hash | 7.76 ms | 11.3 ms (1.46x) | 4.77 ms (0.615x) |
| stencil1d3 | s | hash | 166 ns | 164 ns (0.988x) | 61 ns (0.367x) |
| stencil1d3 | m | hash | 41.5 us | 36.9 us (0.889x) | 18 us (0.434x) |
| stencil1d3 | l | hash | 3.94 ms | 3.85 ms (0.977x) | 2.99 ms (0.76x) |
| box3x3 | s | hash | 366 ns | 346 ns (0.945x) | 296 ns (0.809x) |
| box3x3 | m | hash | 103 us | 54.8 us (0.531x) | 37.1 us (0.359x) |
| box3x3 | l | hash | 6.89 ms | 4.31 ms (0.625x) | 3.57 ms (0.517x) |
| laplace5 | s | hash | 227 ns | 358 ns (1.58x) | 72 ns (0.317x) |
| laplace5 | m | hash | 65.3 us | 64.4 us (0.986x) | 22.2 us (0.34x) |
| laplace5 | l | hash | 4.75 ms | 4.61 ms (0.971x) | 3.46 ms (0.728x) |
| conv3x3 | s | hash | 481 ns | 367 ns (0.763x) | 71 ns (0.148x) |
| conv3x3 | m | hash | 144 us | 62.8 us (0.436x) | 35.5 us (0.246x) |
| conv3x3 | l | hash | 9.73 ms | 4.44 ms (0.456x) | 4.34 ms (0.446x) |
| polymap | s | hash | 234 ns | 276 ns (1.18x) | 119 ns (0.509x) |
| polymap | m | hash | 50.9 us | 65.9 us (1.3x) | 30.6 us (0.601x) |
| polymap | l | hash | 4.26 ms | 4.9 ms (1.15x) | 3.73 ms (0.875x) |
| transpose | s | hash | 132 ns | 363 ns (2.75x) | 115 ns (0.871x) |
| transpose | m | hash | 322 us | 311 us (0.967x) | 78.9 us (0.245x) |
| transpose | l | hash | 29.1 ms | 30.2 ms (1.04x) | 31.7 ms (1.09x) |
| sum | s | hash | 56 ns | 53 ns (0.946x) | 33 ns (0.589x) |
| sum | m | hash | 13.9 us | 12.5 us (0.898x) | 8.12 us (0.585x) |
| sum | l | hash | 1.24 ms | 1.22 ms (0.978x) | 1.9 ms (1.52x) |
| dot | s | hash | 57 ns | 65 ns (1.14x) | 48 ns (0.842x) |
| dot | m | hash | 14.2 us | 13.8 us (0.971x) | 11.9 us (0.836x) |
| dot | l | hash | 1.34 ms | 1.19 ms (0.885x) | 1.88 ms (1.4x) |
| matmul | s | hash | 342 ns | 385 ns (1.13x) | 149 ns (0.436x) |
| matmul | m | hash | 148 us | 152 us (1.02x) | 51.8 us (0.349x) |
| matmul | l | hash | 9.83 ms | 9.94 ms (1.01x) | 3.08 ms (0.314x) |

### Run 2: four threads each (Windows, Rust with Rayon)

Times are medians; the ratio in brackets is beryl (or the other baseline) divided by the first baseline in the row with the same thread count.

| kernel | size | pattern | rust-mt | beryl |
|---|---|---|---|---|
| sq2x2 | s | hash | 13 us | 276 ns (0.0212x) |
| sq2x2 | m | hash | 92.8 us | 22.2 us (0.24x) |
| sq2x2 | l | hash | 4.66 ms | 2.51 ms (0.539x) |
| stencil1d3 | s | hash | 16.8 us | 60 ns (0.00357x) |
| stencil1d3 | m | hash | 50.4 us | 12.1 us (0.241x) |
| stencil1d3 | l | hash | 3.95 ms | 1.87 ms (0.474x) |
| box3x3 | s | hash | 11.6 us | 297 ns (0.0257x) |
| box3x3 | m | hash | 48.2 us | 14.8 us (0.308x) |
| box3x3 | l | hash | 3.21 ms | 2.66 ms (0.828x) |
| laplace5 | s | hash | 11.1 us | 76 ns (0.00687x) |
| laplace5 | m | hash | 42.3 us | 12.1 us (0.286x) |
| laplace5 | l | hash | 3.48 ms | 2.67 ms (0.767x) |
| conv3x3 | s | hash | 12.3 us | 69 ns (0.0056x) |
| conv3x3 | m | hash | 40.9 us | 15 us (0.367x) |
| conv3x3 | l | hash | 3.55 ms | 2.52 ms (0.711x) |
| polymap | s | hash | 16.2 us | 118 ns (0.00727x) |
| polymap | m | hash | 50.6 us | 14.6 us (0.288x) |
| polymap | l | hash | 3.42 ms | 1.76 ms (0.514x) |
| transpose | s | hash | 11.5 us | 92 ns (0.00801x) |
| transpose | m | hash | 47.9 us | 27 us (0.564x) |
| transpose | l | hash | 15.6 ms | 15.5 ms (0.993x) |
| sum | s | hash | 16.2 us | 33 ns (0.00203x) |
| sum | m | hash | 28 us | 5.86 us (0.21x) |
| sum | l | hash | 522 us | 1.02 ms (1.96x) |
| dot | s | hash | 17.2 us | 49 ns (0.00285x) |
| dot | m | hash | 27.9 us | 7.15 us (0.256x) |
| dot | l | hash | 577 us | 959 us (1.66x) |
| matmul | s | hash | 7.7 us | 169 ns (0.0219x) |
| matmul | m | hash | 80 us | 20 us (0.25x) |
| matmul | l | hash | 2.78 ms | 1.13 ms (0.406x) |

### Run 3: four threads each (Linux, C with OpenMP)

Times are medians; the ratio in brackets is beryl (or the other baseline) divided by the first baseline in the row with the same thread count.

| kernel | size | pattern | c | c-mt | beryl |
|---|---|---|---|---|---|
| sq2x2 | s | hash | 406 ns | 1.84 us | 181 ns (0.0986x) |
| sq2x2 | m | hash | 111 us | 55.5 us | 24.3 us (0.438x) |
| sq2x2 | l | hash | 7.83 ms | 3.78 ms | 2.65 ms (0.701x) |
| stencil1d3 | s | hash | 210 ns | 1.81 us | 64 ns (0.0354x) |
| stencil1d3 | m | hash | 57.4 us | 26.9 us | 10.6 us (0.394x) |
| stencil1d3 | l | hash | 5.4 ms | 3.47 ms | 1.72 ms (0.494x) |
| box3x3 | s | hash | 314 ns | 1.96 us | 112 ns (0.0571x) |
| box3x3 | m | hash | 94.1 us | 47.5 us | 15.6 us (0.329x) |
| box3x3 | l | hash | 6.93 ms | 3.75 ms | 3.63 ms (0.967x) |
| laplace5 | s | hash | 247 ns | 1.76 us | 77 ns (0.0437x) |
| laplace5 | m | hash | 79 us | 38 us | 12 us (0.315x) |
| laplace5 | l | hash | 5.73 ms | 3.4 ms | 2.65 ms (0.779x) |
| conv3x3 | s | hash | 345 ns | 1.81 us | 75 ns (0.0415x) |
| conv3x3 | m | hash | 106 us | 54.8 us | 16.7 us (0.304x) |
| conv3x3 | l | hash | 7.72 ms | 3.96 ms | 3.24 ms (0.819x) |
| polymap | s | hash | 233 ns | 1.8 us | 127 ns (0.0705x) |
| polymap | m | hash | 58.3 us | 28.8 us | 15.5 us (0.537x) |
| polymap | l | hash | 7.23 ms | 5.12 ms | 4.15 ms (0.811x) |
| transpose | s | hash | 144 ns | 2.42 us | 106 ns (0.0438x) |
| transpose | m | hash | 333 us | 38.7 us | 32.4 us (0.836x) |
| transpose | l | hash | 47.6 ms | 17 ms | 15 ms (0.879x) |
| sum | s | hash | 39 ns | 1.86 us | 48 ns (0.0258x) |
| sum | m | hash | 9.58 us | 6.5 us | 6.8 us (1.05x) |
| sum | l | hash | 1.46 ms | 642 us | 1.16 ms (1.81x) |
| dot | s | hash | 94 ns | 1.84 us | 58 ns (0.0315x) |
| dot | m | hash | 22.4 us | 10.5 us | 8.29 us (0.789x) |
| dot | l | hash | 1.81 ms | 643 us | 1.35 ms (2.11x) |
| matmul | s | hash | 378 ns | 2.12 us | 222 ns (0.105x) |
| matmul | m | hash | 166 us | 60.1 us | 28.6 us (0.476x) |
| matmul | l | hash | 12 ms | 3.72 ms | 1.28 ms (0.345x) |

### Run 1: beryl against same-interface hand C (one thread each)

| kernel | size | beryl | hand C | hand C / beryl |
|---|---|---|---|---|
| sq2x2 | s | 276 ns | 310 ns | 1.12x |
| sq2x2 | m | 61,324 ns | 66,206 ns | 1.08x |
| sq2x2 | l | 4,770,650 ns | 5,231,000 ns | 1.10x |
| stencil1d3 | s | 61 ns | 94 ns | 1.54x |
| stencil1d3 | m | 18,015 ns | 26,200 ns | 1.45x |
| stencil1d3 | l | 2,993,600 ns | 4,159,700 ns | 1.39x |
| box3x3 | s | 296 ns | 329 ns | 1.11x |
| box3x3 | m | 37,095 ns | 40,912 ns | 1.10x |
| box3x3 | l | 3,565,600 ns | 4,267,250 ns | 1.20x |
| laplace5 | s | 72 ns | 218 ns | 3.03x |
| laplace5 | m | 22,178 ns | 31,562 ns | 1.42x |
| laplace5 | l | 3,456,000 ns | 3,531,700 ns | 1.02x |
| conv3x3 | s | 71 ns | 392 ns | 5.52x |
| conv3x3 | m | 35,465 ns | 40,803 ns | 1.15x |
| conv3x3 | l | 4,341,100 ns | 4,999,800 ns | 1.15x |
| polymap | s | 119 ns | 160 ns | 1.34x |
| polymap | m | 30,570 ns | 38,618 ns | 1.26x |
| polymap | l | 3,729,800 ns | 4,487,650 ns | 1.20x |
