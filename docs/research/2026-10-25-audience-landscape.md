# Who should beryl be for? A first landscape (October 2026)

This is a first pass from web research. Treat it as a starting map, not a market study:
- many sources are vendor material, which is marked;
- several questions are still open (listed at the end);
- `beryl-audience-research-prompt.md` asks Gemini and ChatGPT the same questions
  independently, so their answers can be compared with this one.

## Summary

- **Speed alone will not beat PyTorch.** Training time goes to vendor-tuned GPU matrix
  multiplies and to communication between GPUs. On large runs, communication can dominate
  computation ([MegaScale](https://arxiv.org/pdf/2402.15627),
  [communication study](https://arxiv.org/pdf/2408.10197)).
  - beryl is CPU-only and integer-only, and its measured wins are against single-threaded
    plain C, not against tuned libraries.
  - Going after "faster model training" first would mean competing with NVIDIA, PyTorch,
    Triton and Modular on their home ground, without floating point or a GPU backend.
- **beryl's real differentiator is code that is proved correct and is also fast.**
  Nobody in ML offers that today:
  - verification research there either treats numbers as ideal reals or accepts error
    tolerances ([Volta](https://theory.stanford.edu/~aiken/publications/papers/oopsla26c.pdf),
    [NAO](https://arxiv.org/html/2510.16028v1));
  - GPU memory-safety bugs in LLM inference kernels are an open problem
    ([Model2Kernel](https://arxiv.org/pdf/2603.24595)).
- **The best first audience, in my judgment, is safety-critical edge inference.** That
  means quantized (int8) neural networks and signal-processing kernels running on
  vehicles, drones, defense and industrial devices. It joins the two fields you named:
  - it is AI, and it is real-time and safety-critical;
  - it is integer arithmetic, which is what beryl does today: int8 values multiplied and
    added in 32-bit accumulators;
  - accumulator overflow is a documented source of silent accuracy loss in quantized
    networks ([A2Q, ICCV 2023](https://openaccess.thecvf.com/content/ICCV2023/supplemental/Colbert_A2Q_Accumulator-Aware_Quantization_ICCV_2023_supplemental.pdf),
    [arXiv 2301.13376](https://ar5iv.labs.arxiv.org/html/2301.13376)). beryl's overflow
    proof is exactly the missing guarantee.
  - in practice, current microcontroller toolchains support only INT8
    ([NeurIPS 2025](https://nips.cc/virtual/2025/132986)).
  - certified ML inference is barely served: the offerings found are vendor packages, not
    independent certifications
    ([dSPACE Neural Net Coder](https://www.dspace.com/en/inc/home/products/sw/pcgs/neural-net-coder.cfm),
    [CoreAVI](https://www.electronicspecifier.com/products/artificial-intelligence/software-stack-implements-safety-critical-neural-networks/)).
- **Start as a kernel language embedded in other code, not as a standalone general-purpose
  language.** Futhark's author describes its role as performance-sensitive kernels that
  are only part of a larger system, and notes how little array languages are used outside
  NumPy and MATLAB ([Futhark blog](https://futhark-lang.org/blog/2021-12-19-past-and-present.html)).
  Halide succeeded at Google and Adobe by embedding in C++ and staying focused on image
  pipelines ([Adobe Research](https://research.adobe.com/news/inside-halide-the-open-source-language/)).
  "General-purpose" can be the destination; embedding is the route.

## Audiences

### 1. ML researchers and engineers (training)

**Who.** Researchers and engineers training models at labs, big tech companies and
startups.

**What they use, and why.**
- PyTorch and JAX, for GPUs, automatic gradients and the ecosystem.
- Triton for custom kernels. It is now the default kernel backend under PyTorch's
  `torch.compile` and is used by vLLM, Mamba and DeepSpeed
  ([RFC](https://dev-discuss.pytorch.org/t/rfc-adding-triton-backend-for-aten-operators/2571.md),
  [ML-Triton](https://arxiv.org/pdf/2503.14985)).

**Pain points.**
- Shape changes trigger recompilation.
- Custom kernels compose badly with PyTorch features
  ([dev-discuss](https://dev-discuss.pytorch.org/t/user-defined-kernels-vs-torch-library-custom-op/2113)).
- Triton's coupling to Python makes it hard to integrate elsewhere
  ([PLDI ARRAY 2026](https://pldi26.sigplan.org/details/ARRAY-2026-papers/3/Leveraging-AI-Ecosystem-for-Portable-and-Sustainable-GPU-Kernels-in-HPC)).
- Some operations, such as sort and top-k, are hard to generate
  ([RFC](https://dev-discuss.pytorch.org/t/rfc-adding-triton-backend-for-aten-operators/2571.md)).

**Where beryl fits.** Weakly today. Training time is dominated by matrix multiplies and
communication, at about 40–60% hardware utilization at scale
([course notes](https://tridao.me/cos597a/COS597A_lec1.pdf)). A proved-correct kernel
language helps here only once it has:
- floating point (BF16 and FP8);
- a GPU backend;
- automatic gradients;
- PyTorch custom-op integration.

That is several years of work in the most competitive part of the field.

**Verdict.** A long-term track, not a first audience.

### 2. ML kernel and compiler engineers

**Who.** The people writing Triton and CUDA kernels at labs and inference companies.

**Pain points.** Silent bugs in custom kernels:
- out-of-bounds index arithmetic and data races in LLM inference kernels
  ([Model2Kernel](https://arxiv.org/pdf/2603.24595), [SCuBA](https://arxiv.org/html/2601.21552v1));
- reports of LLM-generated kernels that pass tests but compute the wrong thing
  ([secondary report, unverified](https://groundy.com/articles/when-llm-generated-cuda-kernels-pass-tests-but-get-the-math-wrong/)).

**Where beryl fits.** The proof is directly relevant: no out-of-bounds reads and exact
meaning are beryl's core guarantees. But these users need GPU output, and they work in
floating point, where exact meaning has to be redefined, for example as a fixed order of
reduction.

**Verdict.** A strong second-wave audience once a GPU backend exists. Verifying
AI-written kernels is a timely angle.

### 3. Real-time, safety-critical and defense engineers

**Who.** Avionics, missile defense, automotive, rail and medical-device software teams at
prime contractors and suppliers.

**What they use, and why.**
- C and C++ under MISRA rules.
- Ada and SPARK.
- Qualified model-based code generators: SCADE, whose generator is qualified for
  DO-178C/DO-330 and ISO 26262 (vendor claim,
  [Ansys](https://innovationspace.ansys.com/knowledge/forums/topic/efficient-development-of-safe-avionics-software-with-do-178c-objectives-using-scade-suite/)),
  and Simulink with Embedded Coder
  ([MathWorks](https://www.mathworks.com/solutions/embedded-code-generation/flight-code-generation-aerospace-systems.html)).
- Qualified compilers, such as Ferrocene for Rust: ISO 26262 ASIL D and IEC 61508 SIL 3,
  open source including its qualification documents
  ([Ferrous Systems](https://ferrous-systems.com/blog/ferrocene-26-02-0/)).

**Why they stay.** Certification evidence and tool qualification. Under DO-330, code
generators need qualification, and the rigor is highest when the tool's output becomes
flight software ([LDRA](https://ldra.com/do-330/), [TASKING](https://www.tasking.com/do-330/)).

**Is formal proof valued?** Yes:
- NVIDIA adopted SPARK to prove the absence of runtime errors, including overflow and
  out-of-range memory access, in its most critical code (vendor case study,
  [AdaCore](https://www.adacore.com/blog/proving-safety-at-scale-spark-risc-v-and-nvidias-security-strategy));
- Astrée and Polyspace sell proof of absence of runtime errors as certification evidence
  (vendor claims, [AbsInt](https://www.absint.com/flyers/Astree.pdf),
  [MathWorks](https://www.mathworks.com/videos/part-3-advanced-code-verification-compliance-using-qualified-tools-in-a-do-178c-development-process-1751279622920.html)).

**Where beryl fits.** Strongly. It already proves the absence of overflow and
out-of-bounds reads, rejects bad input before writing output, and has static loop bounds,
which makes timing analysis feasible. Missing:
- floating point, or fixed-point formats;
- a deterministic single-threaded mode;
- MISRA-style C output;
- embedded targets such as ARM Cortex-M/R and DSPs;
- qualification evidence.

**Barriers.** Long sales cycles, qualification cost, and export controls:
- defense-specific items fall under ITAR;
- dual-use software usually falls under EAR, and many items there need no license;
- sharing controlled technology with foreign nationals, even inside the US, can count as
  an export;
- penalties are large ([Kiteworks overview](https://www.kiteworks.com/regulatory-compliance/ear-export-administration-regulations-control/)).

A general-purpose compiler is usually dual-use, but this needs export counsel before
selling to defense.

**Verdict.** The strongest fit for beryl's identity. Its slowness to buy argues for
entering through edge inference (below) and through dual-use markets first, such as
automotive and industrial.

### 4. Edge and embedded AI (quantized inference)

**Who.** Teams putting neural networks on microcontrollers and embedded chips (ARM
Cortex-M, RISC-V) in vehicles, drones, sensors and defense systems
([MCU quantization survey](https://arxiv.org/pdf/2508.15008)).

**What they use.**
- TFLite Micro and the vendor toolchains.
- Model-to-C compilers: Edge Impulse EON, MinUn, dSPACE Neural Net Coder, and ETAS for
  safety-relevant use (vendor claim,
  [ETAS deck](https://images.nuernbergmesse.de/files/6c22a2f6-e71d-ff89-0d01-85b8a06b4cdc.pdf)).

**Pain points.**
- Accumulator overflow and silent accuracy loss with narrow accumulators
  ([A2Q](https://openaccess.thecvf.com/content/ICCV2023/supplemental/Colbert_A2Q_Accumulator-Aware_Quantization_ICCV_2023_supplemental.pdf)).
- Wrap-around versus saturation behavior differs by runtime
  ([PyTorch forum](https://discuss.pytorch.org/t/is-there-anything-wrong-with-the-quantization-math/155245)).
- Certification of the ML component is barely possible today.

**Where beryl fits.** Best of all audiences today:
- the arithmetic is integer, and beryl already handles i32 and i64;
- the overflow proof answers the exact failure the research describes;
- the kernels are convolutions, matrix multiplies and reductions, which beryl already
  compiles and wins on.

**Missing:**
- i8, u8 and i16 types;
- any input range (not just `0..=1023`);
- `max`/`min` and clamping, for ReLU, saturation and requantization;
- several stages per program, to express a layer;
- an embedded C target;
- ONNX import.

**Verdict.** The recommended first audience.

### 5. Scientific, HPC and signal/image processing

**Who and what.** Scientists and engineers using NumPy, Numba, Julia, Halide and C++.

**Where beryl fits.**
- Stencils and reductions are beryl's home ground.
- Halide shows the market for focused image-processing kernels, 3–5× faster than
  hand-written C with shorter code ([PLDI 2013](https://commit.csail.mit.edu/papers/2013/halide-pldi13.pdf)).
- These users mostly need floats and can tolerate unverified code, so the proof is a
  nice-to-have.

**Verdict.** A good source of early users through Python bindings; they will not pay for
proofs.

## Lessons from prior attempts

- **Mojo (Modular).** It reached 1.0 in August 2026 and open-sourced its compiler, though
  outside contributions are not accepted yet
  ([Phoronix](https://www.phoronix.com/news/Modular-Mojo-Open-Source),
  [Wikipedia](https://en.wikipedia.org/wiki/Mojo_(programming_language))). One report links
  this to an acquisition by Qualcomm, which I could not confirm.
  - Lesson: a general-purpose AI language takes years and a very large investment, and
    licensing was itself an adoption barrier.
- **Triton.** It won by embedding in Python and PyTorch and by being much easier than
  CUDA, not by being the fastest.
  - Lesson: integrate with where users already are.
- **Halide.** It won focused domains (camera pipelines, Photoshop) with a clean separation
  of algorithm and schedule.
  - Lesson: one domain, done extremely well, embedded in C++.
- **Futhark and Dex.** They were technically strong but saw little adoption: they started
  as research vehicles, and their ergonomics suffered (verbosity, no rank polymorphism)
  ([Futhark blog](https://futhark-lang.org/blog/2021-12-19-past-and-present.html)).
  - Lesson: ease of use matters as much as speed and soundness.
- **SPARK and Ferrocene.** In safety-critical work, proof and qualification are what sell.
  Ferrocene shows that an open-source toolchain can be qualified and still be
  commercially viable.

## Recommendation

1. **First audience:** safety-critical edge inference and signal processing in integer
   arithmetic. Pitch: proved free of overflow and out-of-bounds bugs, faster than
   hand-written C, for automotive, drones, industrial and defense embedded systems.
2. **Second:** ML kernel engineers, once floats and a GPU backend exist, offering
   verification of hand-written and AI-written kernels.
3. **Avoid for now:** competing on "faster LLM training". It needs floats, a GPU backend,
   automatic gradients and integration with incumbents first, against the best-funded
   teams in the industry.

**General-purpose path.** Grow the language from kernels outward:
1. broaden the kernel language (more types, ranges, operators, stages);
2. host bindings (Python, C, Rust);
3. functions and modules;
4. structured control flow that keeps bounded, provable execution;
5. finally, general data structures.

Keep the guarantee everywhere: if beryl compiles it, it cannot overflow, read out of
bounds or behave unpredictably.

## Open questions

- Market size and willingness to pay for verified edge-inference kernels.
- Whether the incumbents (dSPACE, ETAS, CoreAVI) hold real certificates, and what those
  cost.
- What DO-330 or ISO 26262 tool qualification of a code generator would cost a small team.
- An independent breakdown of attention versus matrix-multiply time in training.
- Export classification of beryl: needs counsel.
