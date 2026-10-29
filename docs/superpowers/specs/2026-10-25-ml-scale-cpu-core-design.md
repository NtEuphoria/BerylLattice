# The ML-scale CPU core: faster single-thread code and larger data

Status: design, 2026-10-25. Builds on `2026-10-19-scale-design.md` (scale-v1, phases 1–2e) and
sits inside Stage 0b of `2026-10-25-beryl-roadmap-design.md`.

## Intent

The founder wants beryl to become a real option for machine-learning training: companies
using it to train better and more efficient models faster, on large data.

The agreed path is the one Triton took. Companies keep PyTorch at first. beryl compiles the
fused kernels inside it, proved correct and free of silent overflow, and grows from there.
Floating point, GPUs and the PyTorch plug-in are the next project. This one builds the CPU
core they stand on. It makes beryl's single-thread code competitive with tuned code, not just
with plain C, at the sizes ML uses.

## Where things stand (measured 2026-10-25, commit `a6d10a1`)

**Machine.** Ryzen 3 3100 (Zen 2, AVX2, no AVX-512 or VNNI), Windows 11 and WSL2 Ubuntu.

**1. Every benchmark so far was built for SSE2.** `bench/run.py` defaults to `-O3` with no
`-march`, so all sides used 128-bit vectors. With `-march=native` (AVX2), on one thread:

| kernel | size | plain C, SSE2 → AVX2 | beryl, SSE2 → AVX2 | beryl / C time, SSE2 → AVX2 |
|---|---|---|---|---|
| matmul | l | 9.52 → 2.00 ms | 3.67 → 1.64 ms | 0.39 → 0.82 |
| sum | m | 13.8 → 2.7 µs | 7.0 → 3.8 µs | 0.51 → **1.41** |
| sum | l | 1.23 → 0.82 ms | 1.11 → 0.87 ms | 0.90 → **1.07** |
| dot | m | 14.0 → 3.0 µs | – → 3.2 µs | – → **1.07** |
| box3x3 | l | 6.92 → 4.47 ms | 3.45 → 3.10 ms | 0.50 → 0.69 |
| laplace5 | l | 4.52 → 4.48 ms | 3.30 → 2.88 ms | 0.73 → 0.64 |
| sq2x2 | l | 7.30 → 3.50 ms | 4.69 → 3.19 ms | 0.64 → 0.91 |
| transpose | l | 29.1 → 28.7 ms | 29.9 → 30.8 ms | 1.03 → **1.07** |

The baselines gain far more from AVX2 than beryl does. Stencils still win, but sums and dot
products now lose, and matmul's lead shrinks from 2.6x to 1.2x. Logs: `.local/avx2/`.
Application Control blocked a few runs; every number above comes from a completed,
oracle-checked run.

**2. The input check costs a fifth to a third of large stencils.** Each kernel was timed
with its range check and with the check removed (WSL, gcc `-O3 -march=native`, one thread,
median of three; `.local/checkcost/`):

| kernel, size | check share of time |
|---|---|
| stencil1d3 l, polymap l | 38% |
| box3x3 l, conv3x3 l, laplace5 l | 32–33% |
| sq2x2 l | 21% |
| sum m, dot m (fused check) | 26–29% |
| sum l, dot l (fused check) | 8% |
| transpose l | 3% |
| matmul l | 1% |

Large inputs are read twice: once to check, once to compute. In cache, the compares
themselves cost, because a sum does one add per value and the check does two compares and
an OR.

**3. Narrow data, 32-bit arithmetic.** Since Phase 2e, kernels read `u8`, `i8` and `i16`
arrays, but every node is computed in 32 bits, or 64 in an i64 program. That gives 8 lanes
per AVX2 instruction instead of 16. Tuned int8 code uses `vpmaddubsw` (u8 × i8, pairs
summed into i16) and `vpmaddwd` (i16 × i16, pairs summed into i32). `vpmaddubsw` saturates:
255·127 + 255·127 clamps to 32767. oneDNN documents this pitfall, and ONNX Runtime added a
checker for it ([oneDNN](https://www.intel.com/content/www/us/en/docs/onednn/developer-guide-reference/2025-1/nuances-of-int8-computations.html)).
Widening to i16 first is exact but about half the speed. beryl knows every value's range,
so it can choose the fast instruction exactly when saturation is impossible. Hand-written
libraries cannot do this safely.

**4. No tiling.** Transpose walks memory with a large stride and loses on one thread. Matmul
has no cache or register blocking, so it is far below what the core can do. A tuned BLAS
uses a packed, blocked layout with a register-blocked micro-kernel
([BLIS](https://www.cs.utexas.edu/~flame/pubs/sc13.pdf)).

**5. Weak baselines.** The plain C and Rust baselines take sizes at run time and store 64-bit
outputs. Matmul has never been compared with a tuned library. NumPy here links OpenBLAS.
PyTorch, whose int8 CPU path uses FBGEMM, is not installed.

**6. Size caps.**
- 2^24 cells per tensor (`scale_family.MAX_CELLS`) and 2^24 terms per sum
  (`reduce_family.MAX_SYMBOLIC_TERMS`).
- The kernel returns the first bad index plus one as `int32_t`.
- All inputs are concatenated into one buffer of one storage type. Mixed `u8`/`i8` is
  therefore impossible, and a caller holding separate tensors must copy them together.
- Large ML tensors do not fit. A 4096 × 11008 weight matrix has 45M values.
- The Python reference interprets every cell, so tests cannot run it at those sizes.

## Goals

1. **Equal flags.** Every benchmark builds all sides with `-O3 -march=native`, records the
   target, and reruns the matched suite, hand C included.
2. **Cheaper checks, contract kept.** By default the check still finishes before any output
   is written, but costs less. (a) Check by block minimum and maximum, two vector ops per
   value. (b) Skip any bound equal to the storage type's limit (done in 2e).
3. **An opt-in fused contract.** A program may declare that its output is unspecified on
   rejection. The check then runs block by block, just before each block is computed, so the
   input is read once. The status is unchanged: 0 only if every input is in range, else the
   exact first bad index plus one. The default contract is unchanged.
4. **ABI v2: one pointer per input.**
   - Each input has its own pointer and storage type, so mixed `u8`/`i8` works.
   - Up to four inputs, which covers a dense layer with weights and bias.
   - An `int64_t` status.
   - Tensors up to 2^31 − 1 cells and sums up to 2^31 − 1 terms.
   - The proof cost stays flat in size.
   - A sampled reference evaluates only chosen output cells, so tests run at full size.
5. **Tiled schedules with a proof rule.** Tiled output loops, k-blocked sums and
   register-blocked cells for matmul. Tiled transpose. Each is a plan the checker proves.
6. **Narrow arithmetic chosen by the proof.**
   - Plans may mark nodes as i16 arithmetic, or mark a product sum as a pair
     multiply-add (`maddubs` or `madd`). The checker proves every marked node, pair and
     partial sum fits.
   - The emitter writes AVX2 intrinsics for marked nodes under `#if defined(__AVX2__)`,
     with the portable C kept as the fallback.
7. **Honest tuned baselines.**
   - OpenBLAS `sgemm`, through NumPy, as the ceiling for matrix multiply, labeled as
     float32 arithmetic.
   - PyTorch's int8 CPU path (FBGEMM: quantized `Linear`, `torch._int_mm`) for int8 layers.
   - Hand AVX2 C for sum and dot.
   - Every loss published.

## Non-goals (this project)

- Floating point, GPUs, autograd and the PyTorch extension. Those are the next project.
- More threads. The pool already scales, so this project is about one core. Tiles must
  still split across the pool.
- Emitting LLVM IR or assembly. The C backend stays; intrinsics go only where a proof
  marks them.
- Packed copies of inputs (BLIS-style packing). Only if tiling plus register blocking
  falls short against OpenBLAS by more than 2x, and then as its own phase.

## Anti-goals

- A faster kernel that is not proved. Every new schedule, width or instruction pattern is
  proposed by an untrusted plan and accepted only by the checker, or lands in the documented
  "argued and tested, not checked" list (the matched report's last section).
- Weakening the default contract silently. The fused contract must be written in the
  source, and it changes the semantic identity.
- Numbers without baselines on equal flags and equal threads, or wins quoted without the
  losses.
- Breaking existing programs. Their meaning and digests stay the same. Generated C may change
  only behind a new codegen version, with the benchmarks rerun.

## Decisions

The founder handed these to me ("do whatever you think is best"). Each is my call.

- **Integers on the CPU first.** Floats change what "exact" means: the proof becomes a
  rounding contract, which deserves its own design. Integer tiling, blocking and narrow
  arithmetic carry over to floats and to GPUs.
- **Fused contract spelling:** `require output_on_rejection = unspecified;`, a new `require`
  form. When present, it is added to the semantic record.
- **ABI v2 replaces the concatenated buffer:**
  `int64_t beryl_kernel_v2(const T0 *restrict in0, ..., OUT *restrict out)`.
  - For single-type programs, `beryl_kernel(const T *input, OUT *output)` stays as a wrapper
    that passes offsets into the joined buffer. Existing drivers, harnesses and tests keep
    working.
  - The wrapper returns `int32_t` and is emitted only when the input count fits.
- **Fused check mechanics.**
  - Before computing a block of output rows, the kernel checks the input rows the block
    newly reads.
  - Rows no output reads are checked at the end, so the status still covers the whole input.
  - On any bad flag, the kernel stops and runs today's ordered scan over every input. That
    returns the exact first bad index even when it lies in a part of an earlier input that
    has not been checked yet.
- **Mixed-type driver:** the standalone driver parses each input's tokens against that
  input's own storage type, in declaration order.
- **Sampled reference:** it evaluates only the chosen output cells. Producer cells are
  computed on demand and cached, with the same exact-integer rules as the full reference,
  which stays the oracle at small sizes. The two must agree wherever both run.
- **Plan format:** new fields (tiles, width marks) go in `beryl-loop-plan-v2`. Version 1 plans
  check and emit exactly as today.
- **Size limits:** 2^31 − 1 cells per tensor and terms per sum. Loop variables stay
  `int32_t` per axis. Cell and index arithmetic stays `int64_t`, as today.
- **Tiling proof rule.**
  - Every output cell is a pure function of its position and is written exactly once. So
    any order of a tiling that covers each cell once gives the same output.
  - The checker accepts a tile record `((v0, T0), (v1, T1))` only in one canonical form:
    full tiles plus clamped edge tiles, which provably partition `H × W`.
  - k-blocking splits a symbolic sum into consecutive ranges. It is already covered: the
    existing bound proves every partial sum fits in any order.
  - Register blocking computes several cells together. It is emission inside a tile, so it
    joins the "argued and tested" list and gets its own mutation tests.
- **Narrow-width proof rule.**
  - A node marked i16 must have an interval inside i16, and so must its operands.
  - A `maddubs` pair needs a u8 operand and an i8 operand, and each pair's sum must lie in
    i16.
  - A `madd` pair needs i16 operands and is always exact for i8 and u8 data.
  - Partial sums keep the existing bound.
  - The plan carries the marks; the checker never infers them, so an unmarked plan behaves
    exactly as today.
- **Baseline tooling:** PyTorch CPU wheel installed into a dedicated virtual environment under
  `.local/`, not globally, after approval.

## Order of work

Each phase is one commit with its own tests, byte-identity checks for unchanged programs,
and a WSL sanitizer run. Benchmarks are rerun after phases 1, 2, 4, 5 and 6.

1. **Flags and baselines.** `-march=native` default with the target recorded; hand AVX2 sum
   and dot; NumPy/OpenBLAS sgemm; rerun the matched suite. Gives the honest starting table.
2. **Cheaper default check.** Block min/max reduction for every preflight and the fused sum
   check. Target: sum m and dot m back to at most C's time.
3. **ABI v2 and larger data.** Per-input pointers, mixed storage, up to four inputs,
   `int64_t` status, 2^31 caps, the sampled reference, and a 4096 × 11008 int8 dense layer
   as the size test.
4. **Fused contract.** The `require` form, block-fused check-then-compute for stencils, maps
   and carry plans. Target: within 5% of the unchecked times above.
5. **Tiling.** tile-v1 plans, tiled transpose (target: faster than C and Rust on one thread),
   matmul with k-blocking and register blocking (target: within 2x of OpenBLAS sgemm).
6. **Narrow arithmetic.** Width marks, `madd`/`maddubs` checks, AVX2 intrinsics, the
   generator proposing marked plans. Target: an int8 dense layer at or above PyTorch/FBGEMM
   on one thread.

## Progress

**2026-10-25.** Scale spec Phase 2f; numbers in the matched report's "AVX2 and the first
speed fixes".
- **Phase 1, partly done.**
  - Benchmarks now build every side for the host CPU by default, Rayon included.
  - OpenBLAS `sgemm` measured on one thread: 388 µs at 256.
  - Not yet: hand AVX2 sum and dot, PyTorch/FBGEMM, and the rerun of hand C.
- **Phase 2, done.**
  - The check is one unsigned maximum per value; a medium sum is now 0.88x C's time, down
    from 1.37x.
  - My call: it does this instead of a block min/max. Min/max saved 15% on that sum; the
    unsigned maximum saved 28%.
- **Phase 5, transpose, done early.**
  - 16 × 16 tiles make it 3x faster, now 0.34x C's time.
  - My call: tiles are an emission strategy on the "argued and tested" list, not yet a
    checked plan field. The tile-v1 plan record follows when matmul blocking needs it.
- **Found on the way:** per-cell sums for weights stored `[out, in]`: 17.6x on an int8 dense
  layer. This is the layout PyTorch uses, so it matters for the ML goal.
- **One thread, AVX2, against C:** 0.70 → 0.59 geomean of beryl's time, 18 of 20 cases
  faster. Two memory-bound losses remain, within 3%.

**2026-10-26.**
- **Phase 1, more done.**
  - The matched suite was rerun on AVX2: hand C with gcc, s, m and l, and C with OpenMP at
    four threads.
  - Rayon and the Windows hand C at the s size could not be rerun: Application Control
    blocked `rustc` and most executables.
  - The pitch numbers now come from this rerun, pending the founder's review.
- **Phase 3a, done.** Scale spec "Phase 3a".
  - Limits rise to 2^31 − 1, with the kernel interface unchanged.
  - The sampled reference is added.
  - The full 4096 × 11008 int8 layer runs natively and matches the sampled reference.
  - My call: the larger limits come first, because they alone admit real layer sizes. The
    ABI v2 items (per-input pointers, mixed u8/i8, four inputs, `int64_t` status) follow as
    3b.
- **Phase 3b, done.** Scale spec "Phase 3b".
  - Each input has its own pointer and storage type, up to four inputs. The status is
    `int64_t`, and the cell limit is per tensor.
  - The size test is a 4096 × 11008 layer with u8 activations, i8 weights and an i32 bias.
  - My call: ABI 2 is used where a program needs it, or on request; ABI 1 stays the default
    for the rest. ABI 1 programs keep byte-identical C, so the published benchmark numbers
    still describe them. ABI 2 becomes the default once the matched suite has been rerun on
    it.
  - Found on the way: the emitter could take an i64 sum's block length from the wrong input
    when an index adds a negative literal. Fixed, with a regression test.

## Verification for every phase

- Reference agreement on full-size programs, through the sampled reference from phase 3 on.
- Mutation fuzzing of every new plan field: wrong tile sizes, overlapping tiles, missing edge
  tiles, false width marks, `maddubs` on pairs that can saturate. Each must be refused.
- Native runs at 1 and 4 threads, plus TSan and ASan+UBSan in WSL.
- The full suite, with failures sorted by host cause. Fix the classifier's case-sensitive
  WinError match first.
- The matched report gets a new dated section per rerun, including losses.

## Left to the builder

- Tile sizes, register-block shape and the block length for min/max checks. Choose them by
  measurement on this machine, and record them.
- How the generator proposes widths and tiles. It is untrusted, so any search works.
- Driver behaviour for programs whose inputs exceed what text input can reasonably carry.
- Whether the four-input limit needs to grow. Not past what a dense layer with bias needs,
  unless a measured kernel asks for it.
