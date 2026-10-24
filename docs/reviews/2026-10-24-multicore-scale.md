# Multi-core scale-v1 and loop-order sums (2026-10-24)

Goal: 5x over C on the benchmark kernels. This records what is physically possible, what was built
and what was measured.

## Ceilings (AMD Ryzen 3 3100: 4 cores / 8 threads, 2 MB L2, 16 MB L3)

| Benchmark | Ceiling | Why |
|---|---|---|
| Process latency (playground table) | about 1.0x | 95% of each run is OS process start, paid by every language |
| Small kernels (35-150 ns) | well below 5x | call overhead plus a mandatory check of every input |
| Large in-cache kernels (m tier) | about 4x per core count, plus codegen gains | compute-bound; scales with cores |
| Large memory-bound kernels (l tier, 16 MB+) | about 2-3x | RAM bandwidth; every stencil lands near 2.6 ms whatever the thread count |

## Changes

1. **Every scale-v1 sum is a loop.** The parser keeps `sum` as a SumExpression. Admission expands
   sums of up to 256 terms into balanced trees only for the small families, so their identities are
   unchanged (`expand_small_sums`). Profile normalization moved to `canonical_profile.py`, which
   brings `frontend.py` under 500 lines.
2. **Row accumulation.** When an output is one sum whose body reads along the column, the emitter
   accumulates a row segment at a time: the sum variable in the outer loop, columns contiguous and
   vectorized in the inner one. Each cell still adds its terms in ascending order. matmul 256 went
   from 18.4 ms to 0.88 ms.
3. **Proven-safe multi-core execution.**
   - A persistent pool runs on logical CPUs minus one; `BERYL_THREADS` caps it.
   - The flattened cell range is cut into 16-aligned chunks, about four per thread, which threads
     claim from one atomic counter.
   - The proved store index `v0*W + v1` writes each cell exactly once, the producer is inlined,
     inputs are read-only and accumulators are local. Chunks therefore never share a written
     location, and the result does not depend on the thread count.
   - The input preflight is parallel too and completes before any cell is computed.
4. **Split reductions.** A single-cell output that is one large sum splits its range across the
   pool. Every partial sum is bounded by the same proof as the whole sum, and the partials are
   combined in a fixed order.

Two concurrency bugs were found and fixed during testing:

- **Start-up race.** A late-starting worker treated the first dispatch as already seen, and the
  dispatch deadlocked. Workers now start from the pre-dispatch generation.
- **Oversubscription.** Using all 8 logical CPUs caused 650 us stalls whenever a worker was
  preempted. The pool now uses one fewer, and chunk claiming means a preempted worker no longer
  blocks the rest.

## Verification

- **Reference agreement.** Four programs (canonical 80x83, box 90x97, matmul 40, sum 200000) were
  run against the reference evaluator at 1 and 8 threads. Each had a good input 20 times and three
  bad inputs (first, middle, last) 3 times, all with timeouts. All matched, with no hangs.
- **Benchmark.** Every benchmark output matched the oracle checksum.
- **Tests.** The scale, reduce, frontend, profile, window, guide, golden-checker, native and
  playground suites pass. The only errors are Application Control blocks, all in the known list.

## Results

Hash and max patterns, median ns. "C" and "hand C" are the existing single-threaded baselines.
beryl uses all cores (7 threads) automatically; the baselines use one. "hand C" has the same i32
interface and input validation as beryl.

| Kernel | Tier | beryl | C | x C | hand C | x hand C |
|---|---|---|---|---|---|---|
| transpose | m 256x256 | 21,213 | 401,775 | **18.9** | - | - |
| matmul | l 256 | 882,300 | 9,502,450 | **10.8** | - | - |
| conv3x3 | m 254x254 | 14,975 | 143,768 | **9.6** | 40,984 | 2.7 |
| matmul | m 64 | 17,628 | 148,894 | **8.4** | - | - |
| box3x3 | m | 13,888 | 103,029 | **7.4** | 41,001 | 3.0 |
| sq2x2 | m 255x255 | 19,928 | 113,850 | **5.7** | 62,660 | 3.1 |
| laplace5 | m | 13,220 | 65,350 | 4.9 | 30,595 | 2.3 |
| conv3x3 | l 2046x2046 | 2,608,650 | 9,420,950 | 3.6 | 3,858,100 | 1.5 |
| stencil1d3 | m 65534 | 13,179 | 42,161 | 3.2 | 29,212 | 2.2 |
| polymap | m 65536 | 14,051 | 43,588 | 3.1 | 45,736 | 3.3 |
| sq2x2 | l | 2,654,050 | 7,550,075 | 2.8 | 4,896,500 | 1.8 |
| box3x3 | l | 2,632,025 | 6,853,700 | 2.6 | 3,843,800 | 1.5 |
| transpose | l 2048x2048 | 13,634,475 | 30,983,025 | 2.3 | - | - |
| sum | m 65536 | 6,984 | 13,864 | 2.0 | - | - |
| laplace5 | l | 2,589,400 | 4,893,250 | 1.9 | 3,614,250 | 1.4 |
| polymap | l 4.2M | 2,585,200 | 4,224,750 | 1.6 | 3,721,450 | 1.4 |
| stencil1d3 | l 4.2M | 2,567,725 | 3,936,650 | 1.5 | 3,526,325 | 1.4 |

- Against plain C: 6 of 17 cases are at 5x or more, and the geometric mean is **4.0x**.
- Against same-interface hand C: the geometric mean is **2.0x**.
- Every l-tier stencil sits at about 2.6 ms, the memory-bandwidth floor.
- sum l and dot m/l are still refused (`ARITHMETIC_OVERFLOW`) until i64 accumulators exist.

## Honest framing for any public claim

- Say "beryl parallelizes automatically and safely; the C baselines are single-threaded". A
  multi-threaded C or OpenMP baseline has not been measured. Against one, the l-tier advantage
  would mostly disappear, because both hit the same bandwidth floor. The m-tier advantage would
  shrink to beryl's single-core codegen edge (1.3-1.5x vs hand C).
- The plain-C baselines write i64 outputs, which inflates the x-C column at memory-bound sizes.
  The hand-C column is the like-for-like one.

## Next levers

- **Non-temporal output stores at the l tier.** These avoid reading output lines before writing
  them; an estimated 1.2-1.3x on memory-bound kernels.
- **i64 accumulators.** These unlock sum l and dot.
- **A tiled matmul schedule**, for cache blocking beyond 256.
