# Response to "Project Axiom: Performance Research Handoff" (cycles 1 and 2)

This responds to the handoff from Beryl Lattice's performance department, written October 23, 2026. Its
measurements came from hand-written C on a shared 2-vCPU ARM VM, profiling commit `6697e84` on
`recovery/axiom-2026-10-17`.

This work is on `feat/bench-native`, which already moved past several of its premises, so each
proposal below says what exists now, what changed, and why. Every number here comes from Axiom's own
emitter, not hand-written C. Each emitted kernel was checked against an independent reference before
timing.

Test machine: AMD Ryzen 3 3100 (4 cores, 8 threads, 2 MB L2, 16 MB L3), Windows 11, clang 22.1.6
`-O3`. Sanitizer runs used WSL2 Ubuntu with gcc.

## Proposal by proposal

| # | Proposal | Status on this branch | Notes |
|---|---|---|---|
| 1 | Independent scalable oracle | **Done, differently** | `bench/oracle.py` defines every benchmark kernel in plain Python and imports nothing from Axiom. `tests/test_scale_oracle.py` enforces that with an `ast` check. It compares 10 scale-v1 programs (600 to 5,000 input cells; stencils, map, transpose, sum, matmul, dot) against the oracle under three input patterns. The handoff's canonical-only oracle is covered by the `sq2x2` case. |
| 2 | Toolchain levers (encode once; one-pass byte count; lazy imports) | **Lever 1 done** | `select_plan` now validates and encodes each candidate once and checks with that digest. Plan digests are unchanged, and the checker still re-admits the source. At 15x15 it went from 190 ms to 143 ms. Earlier interpreter work had already cut the handoff's 639 ms to 190 ms. Levers 2 and 3 are not done. |
| 3 | Range proof plus guarded unchecked emission | **Done for scale-v1, without the fused guard** | The template checker proves every `+`, `*` and partial sum fits i32 for inputs in range, and the emitter uses plain `int32_t` arithmetic (see "The fused guard" below). |
| 4 | Loop-plan checker with symbolic H, W | **Done** (`scale_checker.py`) | It takes 49 checker steps at both 20x20 and 2000x2000, which beats the proposed "within 2x" bar. It also rejects all 400 randomly mutated plans in the new fuzz test. |
| 5 | carry1 as a fourth schedule | **Done as `carry-v1`, generalized to K rows** | See "carry-v1" below. |
| 6 | u16 input storage | **Declined for now** | The native interface takes `int32_t` buffers, and converting costs a full pass. It could return later as an internal staging buffer. |
| 7 | Rerun on Mo's x86 PC | **Done**, with different conclusions | See "x86 versus the ARM VM". |
| 8 | Parallel bands plus a checker split lemma | **Emitter-side parallelism done; split lemma not done** | See "Parallelism and the checker". |

## The fused guard (proposal 3): why it was not adopted

The fused guard is the fastest variant in the handoff, but it computes with out-of-range inputs and
leaves the output unspecified when the flag is set.

Axiom's contract is different, and it is part of the semantic identity
(`boundary: row-major-preflight-preserve-output-first-invalid`). On bad input, every output cell
keeps its original value and the first bad index is reported. A fused guard would have to write
output before it knows the input is valid, which breaks that contract.

Changing it is a language decision, not an optimization. So the preflight stays a separate pass, but
it is vectorized (a branch-free OR reduction) and, for large inputs, parallel. The handoff's point
about u32 wrapping arithmetic is correct and is exactly what a fused variant would need, if the
contract ever changes.

## x86 versus the ARM VM

| Question | ARM VM (handoff) | Ryzen 3100 (this branch, Axiom-emitted) |
|---|---|---|
| Multithreading | about 1.0x | **Large gains in cache.** m tier (256^2 class): 2.5-3.7x over Axiom's own single-thread code. Every stencil ends up 2.2-3.3x faster than same-interface hand C. l tier (2046^2, 16 MB+) hits a bandwidth floor of about 2.6 ms regardless of thread count. |
| Non-temporal stores | 0.9x (slower) | **1.5x for single-row outputs** (4M-cell map and 1-D stencil: 2.57 to 1.67 ms). Neutral for box, conv and laplace; slower for sq2x2. Enabled only for single-row outputs of 8 MB or more. |
| Using every hardware thread | not tested | **Harmful.** All 8 logical CPUs caused 650 us stalls when a worker was preempted. The pool now uses logical CPUs minus one and claims work in small chunks. |

The handoff's warning to "calibrate per machine" was right: two of its conclusions reversed on x86.

## Parallelism and the checker

The handoff proposed proving parallel bands in the checker, with a split lemma. Here the
partitioning happens below the proof instead:

- The checker proves one loop plan.
- The emitter splits that plan's cells into contiguous chunks.
- The plan's proved store index `v0*W + v1` writes each cell exactly once, the producer is inlined,
  inputs are read-only and accumulators are local. Disjoint chunks therefore cannot conflict, and the
  result does not depend on the thread count.

This is an argument about emitter code, not a checked proof. It is backed by testing:

- ThreadSanitizer, AddressSanitizer and UndefinedBehaviorSanitizer runs are clean.
- Four programs cover the pool, row accumulation, the split sum and streaming stores, on good and bad
  inputs at 8 and 1 threads (32 runs).
- 1-thread and 8-thread outputs equal the reference over 20 repeated runs.

A checker-level split lemma is still worth doing; it is the right item for the next independent
review.

Two concurrency bugs were found by testing and fixed before any timing:

- **A start-up race.** A worker that started late skipped the first dispatch, which then deadlocked.
- **Oversubscription stalls.**

## Results on this machine (Axiom-emitted, checksum-verified)

From `docs/reviews/2026-10-24-multicore-scale.md`, plus this round's streaming change:

- **Against same-interface hand C** (single-threaded): geometric mean about 2x across stencils and
  maps. Every m-tier stencil is 2.2-3.3x; every l tier is 1.4-1.8x, bandwidth-bound.
- **Against the plain C baselines** (single-threaded, i64 outputs): geometric mean 4.0x. 6 of 17
  cases are 5x or more, including transpose m 18.9x, matmul l 10.8x and conv m 9.6x.
- **Caveat.** Axiom uses all cores automatically; the baselines use one. A multi-threaded C baseline
  has not been measured.

## Claims (agreeing with the handoff's section 7)

Every number above is an Axiom result: emitted by Axiom from a checked plan, verified against an
independent reference, and timed by the benchmark harness. The single-thread versus multi-thread
caveat must accompany every comparison. Nothing here supports "faster than C" in general.

## carry-v1 (proposal 5)

The handoff suggested a scalar plan with a per-column induction invariant in the checker. That
approach needs a new proof rule for every variant. This branch proves one level up instead.

**The plan.** A `carry-v1` plan has two stages:

1. a producer stage, storing the producer expression over the producer's own loop variables;
2. an output stage, whose producer reads are `('prod', i, j)`, meaning "the producer at
   (r + i, c + j)".

**What the checker proves** (`scale_checker.py`):

- the producer stage equals the producer template;
- every `prod` leaf matches a source read at exactly the output position plus (i, j);
- the window stays inside the producer grid over the whole loop box;
- overflow, by the same interval analysis as direct-v1.

The meaning of a carry plan is therefore the direct plan's meaning.

**The emitter** (`scale_carry.py`) keeps the last K producer rows in a ring on the stack
(K = 1 + largest i; the report's carry1 is K = 2). It computes each producer cell once. That is
sound because a producer value is a pure function of its position. This is an emitter argument, like
the parallel split.

**Testing:**

- Python-runtime and native differential tests, at 1 and 8 threads.
- TSan, ASan and UBSan runs are clean.
- Eight targeted forgeries are rejected: shifted window, window past the edge, changed producer,
  short producer loops, wrong producer index, `prod` in a one-stage plan, reused loop variable,
  swapped stages.
- A 200-mutant fuzz where any accepted mutant must equal the reference.

**Ranking** follows the program's objective, as the small families do:

- `prefer multiplication_ops` ranks by multiplications, then operations, then workspace.
- `prefer plan_workspace_bytes` ranks by workspace first.
- A declared `require plan_workspace_bytes` cap below the ring rules carry out.

**Measured** (Axiom-emitted, same program, direct versus carry):

| Kernel | Size | direct | carry | carry speedup |
|---|---|---|---|---|
| sq2x2 (K=2, the report's stencil) | 255^2 | 18.7 us | 12.8 us | **1.46x** |
| box3x3 (K=3) | 254^2 | 13.7 us | 10.9 us | 1.25x |
| conv3x3 (K=3) | 254^2 | 13.8 us | 11.3 us | 1.22x |
| laplace5 (K=3) | 254^2 | 12.3 us | 10.9 us | 1.13x |
| sq2x2 | 2047^2 | 2.42 ms | 2.39 ms | 1.02x (bandwidth floor) |
| box3x3 | 2046^2 | 2.41 ms | 2.50 ms | 0.96x (noise) |

The handoff measured +23% for carry1 over rows2 on ARM. Here carry beats the inlined schedule by
13-46% at the in-cache size and is neutral when memory-bound.

**Benchmark drafts.** The drafts declare caps written for the small sizes: sq2x2 has 64 bytes, and
box3x3 and conv3x3 have 1024. Those caps are binding, so the official benchmark runs keep direct-v1
for these programs. laplace5 has no cap, but its producer is a plain copy, so the operation count
ranks direct first even though carry measured faster. The cost model could take the number of
streams into account, as the handoff suggested.

## Suggested next steps

1. **A checker split lemma for parallel bands** (proposal 8), so parallelism is proved, not only
   tested.
3. **i64 accumulators,** which unlock sum l and dot m/l, currently refused by the overflow proof.
4. **A multi-threaded C baseline,** to keep the comparison honest.
