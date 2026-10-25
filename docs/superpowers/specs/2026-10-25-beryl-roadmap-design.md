# beryl: from verified kernels to a fundable general-purpose language

Status: approved by the founder on 2026-10-25. Date: 2026-10-25.

Inputs:
- this session's work on the compiler;
- `docs/research/2026-10-25-audience-landscape.md`;
- independent research reports from Gemini and ChatGPT, 2026-10-25, which the founder
  holds and which are summarized here.

## 1. Intent

The founder wants beryl to become an independent, general-purpose language that is:
- faster than C and Rust;
- safe by construction;
- easy to use;
- used for real work in two markets: AI (including making model training faster) and
  defense and real-time systems.

The near-term goal is an angel round. It would fund AI development tools (Claude and
Codex) used as a parallel team of agents, plus compute, so one founder can build at the
speed of a team.

The founder's words: making a language from scratch is impressive; making it faster than
Rust and C is more impressive; proving it can be general-purpose and used, with greater
speed, safety and ease of use and with real applications, "is a real startup foundation."

## 2. The thesis

> **beryl is the language where fast code is proved correct before it runs.**
> If beryl compiles a program, it cannot overflow, read out of bounds, or compute
> anything other than what the source says, and it runs as fast as hand-tuned C or faster.

Why this thesis rather than "a faster language":
- Speed alone is a crowded claim. Mojo, Triton, Halide and CUDA all compete on it, with
  far larger teams.
- Proved speed is rare. No mainstream tool both optimizes aggressively and proves the
  optimized code equals the source. The research found ML verification work either
  treats numbers as ideal reals or accepts error tolerances. Memory bugs in GPU inference
  kernels are an open problem.
- It fits both markets:
  - **defense and real-time** buyers already pay for proof that runtime errors are absent
    (SPARK at NVIDIA, Astrée at Airbus);
  - **AI** has a fresh correctness problem: AI-written kernels that pass tests but compute
    the wrong thing. KernelBench (2025) found frontier models matched the baseline in
    under 20% of 250 workloads.
- It is the founder's operating model too. beryl's architecture is an untrusted planner
  plus a small independent checker. That is exactly what makes it safe to let AI agents
  write optimizations, so the way beryl is built becomes part of the pitch:
  > **"Let AI agents write the fast code. beryl proves it is right."**

## 3. Goals, non-goals and anti-goals

**Goals:**
1. Raise an angel round on honest, impressive, reproducible evidence.
2. Grow beryl into a general-purpose language without giving up its core guarantee.
3. Reach the AI market: first verified inference and fused kernels, then GPU kernels,
   then training.
4. Reach the defense and real-time market through a deterministic, verifiable C output
   mode.
5. Keep beryl independent: its own syntax, compiler and identity. It is also callable from
   C, C++, Rust and Python, so companies can adopt it without rewriting their systems.

**Non-goals for now:**
- Replacing PyTorch or JAX as a whole framework.
- Distributed-training infrastructure (collectives, sharding). Integrate with NCCL and the
  frameworks instead.
- Certifying beryl itself (DO-178C, ISO 26262) before a funded partner needs it.

**Anti-goals.** Doing any of these is a failure even if the code works:
- **Claims that fail technical diligence.** For example:
  - "faster than C" measured as all cores against one;
  - "accelerates AI training" before beryl runs on GPUs;
  - "certified" without a certificate.
  One debunked claim costs more credibility than ten honest ones earn.
- **Weakening the guarantee to add features.** A new feature either keeps the proof, or
  keeps safety by explicit runtime checks (section 5). It never reintroduces undefined
  behavior.
- **Becoming only a Python library.** Interoperability is a doorway, not the identity.

## 4. Constraints

**Team.** One founder plus AI agents. Agents multiply code output. Design decisions,
review and correctness judgment stay with the founder and with the checker.

**Hardware today:**
- a Ryzen 3 3100 (4 cores) on Windows 11, with WSL Ubuntu for Linux and sanitizer runs;
- an RTX 5060 Ti for CUDA work;
- an M5 Pro MacBook Pro for Arm64 work.

**Budget.**
- Before funding: whatever the founder spends on tools now.
- After funding: Claude and Codex top tiers (about $200 a month each, per the founder),
  GPU time, an independent soundness audit, export-control counsel and possibly a first
  hire.

**Brand.** The public name is beryl. The internal codename must not appear in public
material: the website, demos, packages and pitch.

**Legal.** Defense sales bring ITAR and EAR exposure:
- the core compiler stays general-purpose and public;
- the closed defense edition (section 8) may be export-controlled where the public core
  is not, so get export counsel before building it, not only before selling it;
- beryl never takes a customer's controlled data onto its machines;
- get counsel before the first defense conversation that involves technical data.

**Windows Application Control** blocks freshly built executables in the temp folder.
Tests that launch executables must fall back to `.local` or WSL, and the block is never
bypassed.

## 5. The architecture that makes "general-purpose and proved" compatible

Two research reports warned that general features break automatic proofs: unbounded
loops, pointers, data-dependent indexing and floating-point reordering. That is true for
proving everything automatically. beryl therefore uses two safety tiers inside one
language:

| Tier | Where | Safety comes from | Speed comes from |
|---|---|---|---|
| **Proved** | Array kernels with bounded loops, affine or checked indices, bounded integers and defined float semantics | The independent checker proves the absence of overflow and out-of-bounds access, and equivalence to the source, at compile time | Aggressive scheduling, SIMD, multi-core, GPU, fusion, all checked |
| **Checked** | General code: functions, structs, data structures, unbounded loops, I/O | Defined semantics with runtime checks for overflow and bounds (like Ada, and like Rust's debug mode), never undefined behavior | Native compilation; the checker removes every runtime check it can prove redundant |

- A program can mix both tiers.
- The compiler reports which code is proved and which is checked. That report is the
  safety evidence for defense customers.
- This is how SPARK and Ada work, and it answers the decidability concern. General code
  stays safe, and proofs make the hot code fast.

**Floating point.** Exactly equal bits is the wrong goal for float code, because
reordering a reduction changes the result. beryl will define two modes:
- **deterministic:** a fixed reduction order, bit-reproducible across thread counts. This
  is what defense and reproducible training need.
- **fast:** reordering is allowed, with a proved error bound against the deterministic
  result.

Overflow and out-of-bounds proofs still apply in both modes, plus finiteness (no NaN or
infinity) where the input ranges allow it to be proved.

**The trusted path to close.** Today the checker proves the loop plan, but the code that
prints C from it is trusted, along with several emitter optimizations: the exact int32
blocks, the carry ring and the thread split. Stage 0 either brings these under checking
(translation validation of the emitted program against the plan) or states them precisely
as trusted assumptions.

## 6. Roadmap

Every stage ends in a demonstration. Estimates assume the founder plus agents and are
deliberately rough. Agents speed up writing code; they do not speed up design or review
at the same rate.

### Stage 0a: the 1517 Medici application (send by 2026-11-15, decision by end of November)

The founder chose the end of November for more thorough work and revisions. 1517 replies
within two weeks, so the application goes out by about November 15. The three weeks
before that pull two pieces forward from Stage 0b:
- same-thread benchmarks, so the video can state an honest per-core speed result;
- demo B, "AI writes it, beryl proves it."

The video script gets at least two revisions.

[1517 Medici Project](https://www.1517fund.com/medici) terms:
- a no-strings stipend of at least $1K, with no equity taken;
- open to high-school students, college students and dropouts in North America;
- apply by emailing a 1517 team member (firstname@1517fund.com) with a five-minute Loom
  video covering who you are, how you got into the field, why you are dedicating yourself
  to the project, and how the grant would help;
- reviewed on a rolling basis, with replies promised within two weeks.

The page stresses personal drive over polish. Past grantees went on to raise much more:
Pareto raised $4.5M two years later. So Medici is the first step and a relationship with
1517, which also invests in young founders. It is not the round that funds the roadmap:
$1K covers about two and a half months of the two AI tools.

**Deliverables:**
1. **A Loom script, about 5 minutes:**
   - the founder's story;
   - the thesis (section 2);
   - a 90-second live demo:
     1. compile a kernel;
     2. show the checker refusing an overflowing sum, with its "declare the equation i64"
        hint;
     3. fix it and compile again;
     4. show the benchmark chart.
   - what the grant buys: AI development tools.
2. **A short email** to the Medici team, with links to the video and the public
   repository or site. The founder sends it; agents never do.
3. **Fix the public surface before linking it:**
   - the website's codename leak and invalid example;
   - labels that make every speed number say "against single-threaded C".
4. **The claims check:** every number in the video and email follows section 9's "Now"
   row.

### Stage 0b: credible core, for the next and larger raise (estimate 6–10 weeks)

The goal is evidence that survives a skeptical compiler engineer. This is what a
pre-seed round, including a later 1517 conversation, will probe.

1. **Honest benchmarks.**
   - Same-thread comparisons: beryl on 1 thread against C and Rust on 1 thread, and
     N threads against N threads (C with OpenMP, Rust with Rayon).
   - Tuned libraries where the arithmetic contract matches: OpenBLAS or NumPy for
     matmul, OpenCV for filters, CMSIS-NN/XNNPACK-style int8 kernels.
   - Losses are published alongside wins.
2. **Soundness.**
   - Close or document the trusted printer path (section 5).
   - Run a large randomized differential and mutation campaign: over a million plans,
     plus generated programs.
   - Commission an independent review of the checker, `scale-v1`, carry-v1 and the thread
     pool. Paid if funded; before that, a review by a separate agent with a fresh context.
3. **Language breadth that unlocks real kernels:**
   - per-input signed ranges;
   - `u8`, `i8`, `i16` storage;
   - `min`, `max`, clamping, shifts, rounding and saturation with exact specified
     meaning;
   - more inputs;
   - several stages per program.
4. **A deterministic single-threaded mode** with no allocation and caller-supplied
   scratch memory: the defense and real-time profile.
5. **A doorway for users.** `pip install beryl`, a generated C header, and one-call use
   on NumPy arrays.
6. **Three demos:**
   - **A, verified int8 neural-network layer.** A quantized convolution, ReLU and
     requantize on CPU. The overflow proof and the fused stages beat a tuned int8 C
     baseline on a single core and scale across cores.
   - **B, "AI writes it, beryl proves it."** Agents generate many candidate
     optimizations live; the checker rejects the wrong ones with clear reasons; the
     accepted ones are faster. It shows the thesis and the operating model at once.
   - **C, deterministic real-time image or signal pipeline.** A multi-stage filter in the
     single-threaded mode, with a proof report, bit-exact on x86 and Arm, and stable
     timing.
7. **Pitch materials.**
   - Fix the website: the codename leak, the invalid example, mislabeled tables, static
     "live" panels, the stale playground.
   - Write a one-page technical brief and a 10-slide deck with only claims the evidence
     supports (section 9).
8. **Customer signal.**
   - Hold 10–15 conversations with real kernel engineers: AI inference and edge teams,
     imaging, embedded and defense-adjacent dual-use teams.
   - Collect 3 real kernels.
   - Try for one letter of intent or design-partner agreement. Even one transforms an
     angel conversation.

### Stage 1: the angel round

**Pitch.** The thesis (section 2), demos A–C, the honest benchmark table, the roadmap,
customer signal, and the agent-team operating model with its unusually low cost.

**Use of funds:**
- AI development tools;
- GPU compute;
- an independent soundness audit;
- export counsel;
- possibly one senior compiler or verification hire.

The raise amount and timing are open questions (Q1).

### Stage 2: floats, GPUs and the first AI proof point (estimate 4–8 months after funding)

1. **Floating point:** f32 and f64 first, then BF16 and FP16, with deterministic and fast
   modes (section 5).
2. **A GPU backend**, CUDA first. Emit CUDA C or PTX from checked plans; the checker
   proves bounds and race freedom for the GPU schedule. AMD can follow through the same
   plan layer.
3. **PyTorch integration:** beryl kernels registered as PyTorch custom ops, with shape
   and dtype metadata.
4. **Fusion and scheduling** of multi-stage float kernels, such as normalization, softmax
   and attention-style blocks.
5. **Demo D.** A fused kernel on a real model layer, on a rented GPU, that beats
   `torch.compile` and is proved free of out-of-bounds access and races. This is the
   first honest "beryl makes AI faster" result: inference first, then a training step.

### Stage 3: the general-purpose language (estimate 6–12 months, overlapping Stage 2)

1. **The checked tier** (section 5):
   - functions, modules, structs and enums;
   - loops with defined overflow behavior;
   - generics;
   - a small standard library.
2. **Tooling:**
   - a formatter;
   - a language server, for editor errors and completion;
   - a package manager;
   - diagnostics in the style the current compiler already has.
3. **A self-hosted or Rust-hosted compiler and checker,** for speed and auditability. The
   checker stays small and is written for review.
4. **A freestanding embedded C target.** One partner-chosen Arm target, with MISRA-style
   output, plus Frama-C annotations or a proof certificate a third-party tool can check.
5. **Demo E.** A real application written fully in beryl: for example a real-time sensor
   pipeline, or a command-line data tool. It shows general-purpose use, with the
   proved/checked report.

### Stage 4: training and assurance at scale (estimate 12–24 months)

1. **Gradients:** automatic differentiation for proved kernels, with checked backward
   kernels.
2. **Formats and parallelism:** FP8, and multi-GPU kernels. Communication stays with
   NCCL and the frameworks.
3. **Demo F.** A full training run where beryl kernels cut measured end-to-end time,
   reported as an end-to-end percentage, not a microbenchmark.
4. **Defense and real-time.** Find a funded design partner. Plan qualification of the
   checker, not the whole compiler, as the evidence strategy (DO-330, DO-333 and NASA
   guidance on qualifying checkers), with counsel and a certification consultant. This is
   where the closed defense edition (section 8) is built.

## 7. Operating model: a founder with an agent team

**Workstreams in parallel**, each with its own branch or worktree, spec and tests:
- language and frontend;
- checker and soundness;
- backends (C, GPU, embedded);
- benchmarks and evidence;
- interop and tooling;
- website and pitch.

**Rules that keep agents safe:**
1. Spec first: the founder approves each design.
2. The checker and the differential tests are the gate. Nothing merges if the checker
   rejects, the tests fail, or the identity of existing programs changes without a
   reason.
3. A separate review agent reads every change to the trusted parts: the checker,
   emitters and runtime.
4. Benchmarks run on a schedule, and regressions block merges.
5. The founder merges. Agents never push or publish on their own.

**Measure the model itself:** features shipped per week, defects caught by the checker
and by reviews, and cost per month. Those numbers belong in the pitch as evidence that a
very small team can execute.

## 8. Customer and funding strategy

- **Angels look for** four things:
  - a founder who ships, which the repository history shows;
  - a demo that works live;
  - honest numbers;
  - a believable first customer, with a big vision on top.
  The research is unanimous that breadth without proof reads as unfocused, so the pitch
  leads with the proofs (demos A–C) and puts the breadth in the roadmap.
- **The first paying motion is a design-partner pilot:** one customer kernel, delivered
  verified and faster, for a fixed fee. Candidates, in order:
  1. edge AI and inference teams with int8 kernels;
  2. imaging and inspection software teams;
  3. dual-use embedded and real-time teams (automotive, drones, industrial);
  4. defense primes, once counsel and a partner exist.
- **AI training companies** are approached at Stage 2 with demo D, not before.

### The defense edition (decided 2026-10-25)

beryl for defense and government real-time work is a closed, application-only edition
built on the same architecture. The split follows the untrusted-planner, trusted-checker
design:

| Open (public) | Closed (defense edition) |
|---|---|
| The language and its reference semantics | The aggressive planners and schedulers |
| The checker, the trust root | The deterministic real-time backend and timing analysis |
| The public C backend and the guide | Certification evidence packages, and support |

- Every plan the closed edition produces is still proved by the open checker, so customers
  and evaluators can verify results without trusting closed code.
- The edition is sold as proved, deterministic and bounded-latency. Any speed claim needs
  measured numbers under the claims policy (section 9).
- **Access by application.** The application records who the applicant is, their
  country, the end use, and a restricted-party screening result. It doubles as the export
  screening step. Counsel sets the exact criteria.
- **Before building it:** export counsel decides whether the edition falls under EAR or,
  if it is specially designed for military use, ITAR. ITAR could limit who may work on
  the code and which cloud tools may touch it.
- **Timing.** No code exists yet. Work starts with the Stage 4 defense item or a funded
  defense design partner, whichever is first. The website and pitch do not announce the
  edition until it exists.
- **Licensing.** The repository has no license yet. The public part gets one when it is
  opened, typically a permissive or Apache-2.0 license in an open-core model.

## 9. Claims policy

| Stage | May claim | May not claim |
|---|---|---|
| Now | "Checked integer kernel compiler; on our 4-core machine, faster than single-threaded C in 30/30 benchmarks" | "Faster than C", "general-purpose", "for AI training", "certified" |
| After Stage 0 | Same-thread and same-core results as measured; "proved free of overflow and out-of-bounds for these programs, assuming [listed trusted parts]" | Anything about GPUs or training |
| After Stage 2 | "Faster than `torch.compile` on [named kernel and GPU], verified free of races and out-of-bounds" | "Speeds up AI training" until demo F |
| After Stage 3 | "General-purpose language with proved kernels and checked code" | "Certified" without a certificate |

## 10. Risks and stop signals

**Risks:**
- Same-thread benchmarks may show beryl's per-core lead is small. Mitigation: lead with
  verified fusion and scheduling, where the advantage is structural.
- GPU performance against cuBLAS and FlashAttention is very hard. Target fused and
  irregular kernels that libraries do not cover, not general matrix multiply.
- A soundness bug found after launch would be very damaging. Mitigation: the audit and
  the mutation campaign come before claims.
- Founder bandwidth. Mitigation: the operating-model rules, and a strict stage scope.

**Stop or change course if:**
- every kernel the conversations collect needs features two stages away;
- matched benchmarks show no advantage anywhere;
- the checker cannot be extended to floats or GPU schedules without losing soundness;
- nobody commits to a pilot after demos A–C.

## 11. Decided and left open

**Decided by the founder:**
- beryl is an independent, general-purpose language;
- funding comes first;
- AI agents are the development team;
- AI, including training, and defense/real-time are the target markets;
- beryl is callable from other languages;
- defense and government real-time work gets a closed, application-only edition, with the
  checker kept open (section 8).

**My calls,** for the founder to check:
- the thesis wording;
- the two safety tiers;
- the two floating-point modes;
- demos A–F;
- the stage order, with CPU proofs before GPUs and inference before training;
- CUDA as the first GPU target;
- the claims policy;
- the design-partner-first sales motion.

**Left to the builder:**
- the syntax of the checked tier;
- the IR design for GPU plans;
- the benchmark harness extensions;
- which int8 layer demo A uses;
- the package and tool names.

## 12. Founder's answers (2026-10-25) and what they change

- **Funding.** The first target is the 1517 Medici Project, at least $1K, by the end of
  November.
  - This adds Stage 0a.
  - The larger raise that funds the roadmap moves after Stage 0b.
  - To confirm: the founder fits the program's high-school, college or dropout
    eligibility.
- **Contacts.** No existing contacts, but the founder is willing to network. The
  greater-Boston area (the founder lives in Revere, MA) is unusually strong for beryl:
  - compilers and programming languages: MIT CSAIL's COMMIT group, where Halide and TACO
    came from, plus Boston-area PL and compiler meetups;
  - defense R&D: MIT Lincoln Laboratory, Draper, MITRE, Raytheon;
  - robotics and edge AI companies.
  Stage 0b's conversations start there.
- **Hardware.**
  - An **RTX 5060 Ti**: Stage 2's CUDA backend and demo D can be developed locally on a
    current NVIDIA GPU. Large-model comparisons still need rented time later.
  - An **M5 Pro MacBook Pro** gives an Arm64 target now: NEON code, and the
    x86-against-Arm bit-exact half of demo C. Apple Metal is a possible later backend.
- **Time and location.**
  - beryl is one of the founder's main projects; the estimates assume substantial but
    not full-time hours.
  - The founder is US-based, so US export rules apply. Collaborators who are foreign
    nationals matter only once controlled technical data is involved, which beryl avoids
    by design.

## 13. Funding map (added 2026-10-25)

Target dates are set to be realistic for one founder working substantial but not full-time
hours alongside the engineering stages. Program terms change. Check each program's own page
before applying; sources are in the notes column, with secondhand ones marked.

### Order and dependencies

The sequence below is ordered by what each step unlocks:
- **Medici and Emergent Ventures** need only a person and a project.
- **Incorporation** unlocks compute credits and SBIR.
- **Python bindings and floating point** unlock the science track.
- **A design partner** strengthens everything after Medici.

### Dated plan

| target date | step | track | needs first | what it brings | notes |
|---|---|---|---|---|---|
| **2026-11-15** | Send the 1517 Medici application | all | eligibility confirmed (Task 0), Loom recorded | at least $1K, no equity; a relationship with 1517 | [1517fund.com/medici](https://www.1517fund.com/medici); replies within two weeks |
| **2026-11-29** | Follow up with 1517 if there's no reply | all | — | — | one short message |
| **2026-12-13** | Apply to Emergent Ventures | AI (all) | the Medici video and story, reused; a written proposal of at most 1,500 words | a grant or fellowship of unpublished size | [Mercatus](https://www.mercatus.org/economic-insights/expert-commentary/application-process-opens-emergent-ventures); form details and reply times are secondhand ([guide](https://hub.causo.ai/guides/how-to-apply-to-emergent-ventures-2026)) |
| **2027-01-31** | Hold 10 conversations with kernel engineers and collect 3 real kernels (Stage 0b) | all | the matched-benchmark report; demos A–C in progress | design-partner leads; evidence for every later application | Boston: MIT CSAIL compiler groups, Lincoln Laboratory, Draper, robotics and edge-AI firms |
| **2027-01-31** | Decide on incorporation, with professional advice | AI, defense | — | — | an LLC or C-corp; this document makes no recommendation on structure |
| **2027-02-28** | Incorporate; get an EIN and a SAM.gov registration (UEI) | AI, defense | the decision above | eligibility for credits programs and SBIR | allow about 4 weeks for SAM.gov; it is free to register |
| **2027-03-14** | Apply to NVIDIA Inception | AI | a company, a website, one listed developer | partner cloud credits and GPU discounts; no fee, no equity | [requirements](https://www.thundercompute.com/blog/nvidia-inception-program-guide) (secondhand); a missing developer listing is a common rejection reason |
| **2027-03-14** | Apply to the cloud providers' startup credit programs | AI | a company | compute for Stage 2 (GPU backend) | check current terms per provider |
| **2027-03-31** | Submit an NSF SBIR Project Pitch | defense, real-time (dual-use) | a company; the Stage 0b evidence | an invitation to send a full Phase I proposal | [NSF 26-510](https://www.casrai.org/news/nsf-sbir-sttr-fy26-relaunch); pitches are reviewed in about 3 weeks |
| **2027-04-15** | Hold a pre-seed conversation with 1517 Fund, or other early investors | all | the Medici outcome; Stage 0b complete; ideally one design partner | the round that funds Stages 1–2 | builds on the Medici relationship |
| **Summer 2027** (first NSF deadline after 2027-06-01) | Send the full NSF SBIR Phase I proposal | defense, real-time (dual-use) | the invitation; Research.gov registration | up to $305,000 for 6–18 months | [Phase I size](https://grantedai.com/blog/nsf-sbir-sttr-nsf-26-510-july-27-deadline-305k-phase-i-instrumentation-pilot-startup-strategy-2026). The 2027-03-04 deadline is too close to incorporation to be realistic, so this targets the next one |
| **2027-09-30** | Apply for NumFOCUS affiliation | science | `pip install beryl`, f32 and f64 support, a few scientific users | access to Small Development Grants (up to $10,000 per project in 2025) | [NumFOCUS projects](https://numfocus.org/projects-overview); grant calls run about 3 times a year |
| **Late 2027** | Look at military SBIR topics (AFWERX, DIU) | defense | an NSF Phase I outcome or a defense design partner; export counsel | defense-specific funding | only with counsel and a partner |
| **2028** | Apply to Sloan or Chan Zuckerberg open-source science funding | science | an established scientific user base | larger multi-year grants | for projects scientists already depend on |

### What would change these dates

- **A design partner** found early moves the NSF pitch and the pre-seed conversation up by
  about a month each.
- **No reply from Medici or Emergent Ventures** changes nothing downstream; neither blocks
  another step.
- **If incorporation slips**, every step from Inception onward slips with it. The NSF full
  proposal then moves to the deadline after summer 2027.
- **The science track** depends on Stage 3 work (bindings) and Stage 2 work (floats), not on
  calendar dates. If those land early, NumFOCUS moves up.
