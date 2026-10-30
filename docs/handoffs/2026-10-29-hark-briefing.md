# Briefing for Hark: beryl, as of 2026-10-29

This brief brings you up to date on beryl: what it is, what changed from 2026-10-24 to
2026-10-29, the rules for working on it, and what comes next. It is self-contained; the
linked documents hold the details.

## What beryl is

beryl compiles array kernels to C and proves each one before it emits it.

- A program states exact integer equations over arrays, plus the range each input may hold.
- An untrusted planner proposes loop schedules ("plans"). A checker proves each plan
  against the source: reads stay in bounds, nothing overflows, and the result is exact.
  Only proved plans become C11.
- Proofs work by template, so checking costs the same at any data size.
- The current family is `scale-v1`: stencils, maps, reductions, transposes, matrix
  multiplies and dense layers, on integers, on the CPU, with a thread pool.

**The goal**, in the founder's words: a viable option to replace or accelerate PyTorch for
ML training on large data. The first step is to plug in as a compiler for proved, fused
kernels, the way Triton does. The current project is "integers on the CPU". Floats, GPUs
and the PyTorch extension come after it.

**Where it stands:** a research prototype on branch `feat/bench-native` of
`github.com/NtEuphoria/BerylLattice`. It is not merged to `main`.

## What changed, 2026-10-24 to 2026-10-29

Each item is one commit on `feat/bench-native`, oldest first.

1. **i64 equations** (`b49d4ec`). Equations may compute in i64. Sums run in exact int32
   blocks, widened once per block.
2. **The Medici sprint** (`f698d1b`). Checked candidate plans, the matched benchmark suite
   against C, Rust, OpenMP and Rayon, and the pitch drafts.
3. **Per-input ranges, and a fused input check for whole-input sums** (`16188c0`).
4. **min, max and clamp** (`3a53961`).
5. **The closed defense edition** in the roadmap (`4b3b0f4`).
6. **Right shifts and rounding:** `shr` and `shr_round` (`46381e3`).
7. **u8, i8 and i16 storage** for inputs and outputs (`a6d10a1`).
8. **Speed work** (`9a8d7c9`).
   - AVX2 builds by default.
   - The input check is one unsigned maximum per value.
   - Transposes run in 16 × 16 tiles.
   - Dense layers with weights stored `[out, in]` keep one sum per cell, which was 17.6x
     faster on an int8 layer.
9. **Pitch numbers from the AVX2 rerun** (`06c6e9d`). Against hand-written C with the same
   interface: faster in 16 of 18 cases with gcc (1.14x), and in 12 of 12 with clang
   (1.72x). Against C with OpenMP at four threads: faster in 19 of 20. The losses are
   published too. **These claims await the founder's review.**
10. **Large data, and one pointer per input** (`0341abe`).
    - Arrays and sums go up to 2^31 − 1 cells, up from 2^24.
    - A sampled reference checks chosen output cells of full-size data.
    - ABI 2 gives each input its own pointer and type (u8 activations with i8 weights work),
      allows up to four inputs, and returns an `int64_t` status.
    - Existing programs still generate byte-identical C.
    - A full 4096 × 11008 layer runs natively and matches the reference.
    - Also fixed a latent emitter bug: an index like `y[0, j-1]` could take the wrong
      input's range.

**Uncommitted as of this brief:** a new top-level `README.md`, an Apache-2.0 `LICENSE`, a
roadmap note on the license, and this file.

## Where things are

| what | where |
|---|---|
| compiler source | `axiom/src/axiom/` (internal folder name); the C emitter is `scale_c.py`, the checker `scale_checker.py` |
| public CLI | `python tools/beryl.py check|native ...` |
| tests | `axiom/tests/`; run `cd axiom && PYTHONPATH=src python -m unittest discover -s tests -t .` |
| the current project's design | `docs/superpowers/specs/2026-10-25-ml-scale-cpu-core-design.md` (goals, decisions, order of work, a dated progress log) |
| per-phase detail | `docs/superpowers/specs/2026-10-19-scale-design.md` (one section per phase, newest first) |
| the company roadmap | `docs/superpowers/specs/2026-10-25-beryl-roadmap-design.md` (stages, the defense edition, the claims policy, the funding map) |
| benchmark numbers | `docs/reviews/2026-10-25-matched-benchmarks.md` |
| pitch drafts | `docs/pitch/` |
| scratch logs and scripts | `.local/` (git-ignored) |

## Rules for working on it

- **Naming.** The public name is **beryl**, lowercase. The codename "axiom" never appears in
  public material: the website, video, email, demo output and pitch docs. The code folder
  and Python package keep the old name internally.
- **Honesty about claims** (roadmap section 9).
  - Every public number needs measured, matched baselines with equal flags and threads.
  - Losses are published with the wins.
  - The founder reviews public numbers before use.
  - What the checker proves is kept separate from what is only "argued and tested".
- **Correctness.**
  - A new schedule is accepted only when the checker proves it, or when it is added to
    the documented "argued and tested" list with its own tests.
  - Existing programs keep their meaning, their digests, and their generated C. Any
    change to the C needs a new codegen version and a benchmark rerun.
- **Testing.**
  - Write the test first and watch it fail.
  - Run native tests at 1 and 4 threads.
  - Run TSan and ASan+UBSan in WSL.
  - Run the full suite and sort failures by host cause with
    `tools/classify-test-failures.py`.
- **Git.**
  - Commit only when asked. Push only with explicit approval, and an approval covers
    that push only.
  - Never commit `.swarm/`, `.claude-flow/`, `.blender-toolkit/` or `sessions/`.
  - Commit messages end with the co-author line the founder's tools require.
- **Agents.** Never send email, post publicly or push on your own.
- **Windows Application Control** sometimes blocks freshly built executables and `rustc`
  (WinError 4551, exit `0xc0e90002`).
  - Never bypass it.
  - Native tests skip when blocked.
  - Run native work in WSL instead, for example
    `wsl python3 /mnt/c/.../script.py`. WSL has gcc, but no Rust.
- **The founder** prefers plain language, and has handed technical decisions to the agent
  ("do whatever you think is best"). Mark each such decision as your call in the design
  docs.

## What comes next

In the order of the current project's design:

1. **Phase 4: the fused contract.** This is the next item; none of it is written yet.
   - A program may declare `require output_on_rejection = unspecified;`. It goes into the
     program's semantic identity.
   - With it, the input check runs block by block, just before each block is computed, so
     the input is read once.
   - The status stays exact: on any bad flag, the kernel runs the ordered scan to find the
     first bad index.
   - Target: within 5% of the unchecked times for stencils, maps and carry plans.
2. **Phase 5: tiling for matrix multiply.** k-blocking and register blocking as checked
   plans. Target: within 2x of OpenBLAS `sgemm`.
3. **Phase 6: narrow arithmetic.** i16 and `maddubs`/`madd` marks proved by the checker,
   with AVX2 intrinsics. Target: an int8 dense layer at or above PyTorch/FBGEMM on one
   thread.
4. **Leftovers from phase 1.**
   - Hand-written AVX2 sum and dot baselines.
   - PyTorch/FBGEMM and OpenBLAS baselines, set up in a virtual environment under
     `.local/`, after approval.
   - Rayon and Windows reruns once Application Control allows them.
   - Making ABI 2 the default, after a benchmark rerun on it.

## Open items for the founder

- Review the new benchmark claims before they go into the pitch or the website.
- The website still shows the old SSE2 numbers. Its source is not in this repository.
- Medici application (deadline 2026-11-15). Confirm eligibility on 1517's Medici page, and
  name the email's recipient: the draft has a `[firstname]@1517fund.com` placeholder.
- The defense edition needs export counsel (EAR or ITAR) before any code exists.
