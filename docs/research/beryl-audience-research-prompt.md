# Research prompt: who should beryl be for?

Paste everything below the line into Gemini (Deep Research) or ChatGPT (deep research).
Each tool researches on its own; compare the answers afterwards.

---

You are a market and technical researcher. I am building a programming language called
**beryl** and need to decide which users to build it for first, and what it must do to be
better than the tools they use today. Please research this thoroughly using current
sources (2024-2026 where possible), and be skeptical: I would rather hear that an idea
will not work than be flattered.

## What beryl is today (accurate as of October 2026)

beryl is a small, *checked* compiler for numeric array kernels. A program declares fixed
shapes, typed inputs, one intermediate array and one output, written as equations over
indices, for example a 3x3 blur, a dot product or a matrix multiply:

```
module dot;
shape H = 1;
shape W = 1;
input x: i32[1,4096] in 0..=1023;
input y: i32[1,4096] in 0..=1023;
let t: i64[r in 0..H,c in 0..W] = sum(k in 0..4096: x[0,k]*y[0,k]);
output d: i64[r in 0..H,c in 0..W] = t[r,c];
```

What makes it different:

- **Every compiled program is proved safe before code is emitted.** An independent
  checker re-reads the source and proves the generated loop plan computes exactly the
  source's meaning, that no read goes out of bounds, and that no addition or
  multiplication can overflow its declared integer type for any input in the declared
  range. The proof's cost does not grow with array size.
- **Bad input is rejected safely.** All input is validated before any output is
  written; on bad input the output is left untouched and the first bad index is
  reported.
- **It generates fast C.** Output is vectorizable C11, run on all CPU cores through a
  built-in thread pool, with optimizations such as reusing intermediate rows,
  non-temporal stores, and exact 32-bit blocks inside 64-bit sums.

Measured speed (AMD Ryzen 3 3100, 4 cores, clang 22): against straightforward
*single-threaded* C and Rust implementations of the same kernels, beryl is faster in 30
of 30 cases against C (geometric mean about 2.9x; up to 10x for matrix multiply and
convolution) and 29 of 30 against Rust. Important caveats: beryl uses every core while
those baselines use one; it has not been compared against tuned libraries such as
OpenBLAS, MKL, oneDNN or PyTorch's CPU kernels; and it has no GPU backend.

Current limits:

- integers only (i32 and i64), no floating point;
- every input must be in exactly the range 0..=1023;
- no `max`/`min`, comparisons or conditionals;
- one intermediate stage and at most two inputs per program;
- shapes fixed at compile time, up to 2^24 cells;
- CPU only, no GPU or embedded targets yet;
- no automatic differentiation;
- used through a command-line compiler (Python) that emits C; no Python, PyTorch or
  NumPy bindings yet;
- the newest large-size features have not yet had an independent review.

## The goal

I want beryl to grow into a general-purpose language and to "branch out" into fields
where speed matters. Two I am considering:

1. **AI/ML**: making models faster to train and run.
2. **Defense and other real-time, safety-critical systems**: for example missile
   defense, where computations must be fast, predictable and correct.

Others (scientific computing, signal and image processing, finance, robotics,
automotive, embedded/edge devices) are open.

## What I need you to research

For each candidate audience (at least: ML researchers and engineers, ML kernel and
compiler engineers, real-time/safety-critical/defense engineers, scientific and HPC
programmers, signal/image processing engineers, and edge/embedded developers):

1. **Who they are.** Roles, rough number of people, the kind of organization they
   work in.
2. **What they use today, and why.** Name the actual tools, for example PyTorch, JAX,
   TensorFlow, Triton, CUDA, cuDNN/cuBLAS, TVM, XLA/OpenXLA, Mojo, Halide, Taichi, Julia,
   Numba, NumPy, Futhark, Dex, C/C++ under MISRA or AUTOSAR, Ada/SPARK, MATLAB/Simulink
   with Embedded Coder, SCADE, Rust in safety-critical work. For each, say what problem
   made people choose it, and what keeps them there: ecosystem, hardware support,
   hiring, certification, habit.
3. **Their real pain points, with evidence.** Cite developer surveys, conference
   talks, postmortems, issue trackers, forum and Reddit threads, and papers. Look
   especially for:
   - silent numerical bugs, overflow, out-of-bounds reads and race conditions in
     custom kernels;
   - nondeterminism and run-to-run reproducibility;
   - the difficulty of writing fast GPU kernels;
   - certification cost (DO-178C, ISO 26262, IEC 61508, MIL-STD-882E and similar);
   - worst-case execution time analysis;
   - porting code between hardware vendors.
4. **What would make them switch.** What a new tool would have to offer, how much
   better it must be, and what it must interoperate with from day one, such as being
   callable from PyTorch, emitting MISRA-compliant C, or targeting a specific chip.
5. **Where beryl's specific strength fits.** That strength is proved-correct code
   (no overflow, no out-of-bounds, exact semantics) that is also fast. Say honestly
   where that is a must-have, where it is a nice-to-have, and where nobody will pay
   for it.

Also research these questions:

6. **Prior attempts and lessons.** What did these projects promise, who adopted them,
   where did they stall, and what can beryl learn?
   - Triton (OpenAI);
   - Mojo (Modular);
   - Halide;
   - TVM;
   - Futhark;
   - Dex (Google);
   - Taichi;
   - Julia's adoption in ML;
   - SPARK/Ada;
   - CompCert;
   - verified compilers and formally verified ML kernels in general.
7. **AI/ML reality check.**
   - Where does training and inference time actually go today: matrix multiplies,
     attention, communication, data loading, memory bandwidth?
   - Which of those could a new kernel language realistically improve?
   - Would a verified kernel language help ML training at all, or only inference and
     edge deployment?
   - What would beryl need first: floating point (FP32, BF16, FP8), GPU code
     generation, automatic differentiation, kernel fusion, or PyTorch custom-op
     integration?
8. **Defense and real-time reality check.**
   - What languages and toolchains do real-time defense and aerospace systems use
     today?
   - How is software qualified or certified, and what does tool qualification
     (for example DO-330) require of a compiler or code generator?
   - Is formal proof of absence of runtime errors valued (cite SPARK, Astrée, Frama-C
     users)?
   - What hardware do these systems run on: CPUs, DSPs, FPGAs, GPUs?
   - What legal and export-control considerations (ITAR, EAR) apply to a small team
     selling tools into this market?
9. **Competitive positioning.**
   - For the two or three most promising audiences, what is the smallest version of
     beryl that would be genuinely useful to them, and which incumbent it would
     displace or complement?
   - Should beryl be a standalone general-purpose language, or a kernel language
     embedded in a host language (Python, C++, Rust)? Give evidence either way.

## How to answer

- Start with a one-page summary: your top recommended first audience, the second,
  and the one to avoid for now, each with the reasoning.
- Then give one section per audience, then sections 6-9.
- End with a ranked list of the 10 capabilities beryl should add first for your
  recommended audience, each with why and how you would measure success.
- Cite a source for every factual claim, with links. Mark clearly where you are
  inferring or estimating rather than citing.
- Prefer primary sources (official docs, papers, standards bodies, company
  engineering blogs, surveys) over secondary summaries.
- Where sources disagree, say so.
- Do not soften conclusions to be encouraging.
