# beryl research plan

*Written 2026-11-02 for beryl's founder. It is built from five literature sweeps (verified compilers, saturating SIMD, bugs in the trusted base, AI-written kernels, venues) and the repository's own docs. Three separate verification passes then checked every reference and venue claim. All 48 references exist. Where a pass found a wrong or incomplete detail, the plan below has been corrected, and the reference list notes how each corrected entry was confirmed. Several references are 2025–2026 preprints that are still being revised, so the novelty verdicts are only valid as of 2026-11-02. Check every reference again yourself before you cite it.*

> **Use this plan as advice, not as text to submit.** An AI wrote this document. STS, ISEF and NHSJS forbid AI-written prose in what you submit, and ACM and arXiv make you responsible for every word. Do not copy any sentence here, including the sample abstract in section 3, into an application, research plan, abstract, poster or paper. Write those yourself.

---

## 1. Bottom line

- **The core design is known.** An untrusted optimizer proposes, an independent checker accepts or rejects, and only accepted results are compiled. This is the "verified validator" pattern from CompCert [7] and Tristan & Leroy [8]. It goes back to proof-carrying code [14] and translation validation [15].
  - STOKE [32] and CryptOpt [33] use the pattern with random search.
  - LLM-Vectorizer [30] and LLMLift [31] use it with an LLM as the proposer.
  - ComPilot [34] uses a weaker form. An LLM proposes, but its gate is the compiler's legality and dependence check plus measured speedup, not a proof of equivalence.
  - Do not present "AI proposes, a proof decides" as new.
- **Most of the parts are known too.**
  - Checking cost that does not depend on data size is normal for any checker that works over symbolic sizes (Exo [5], ATL [6], TensorRight [43]).
  - Interval bounds over affine indices are in Halide [1] and Exo [5].
  - Proving no overflow from declared input ranges is in Fiat Cryptography [16], with a Coq proof.
  - Using a saturating instruction only when bounds rule out saturation is in Pitchfork [17] and Rake [18].
  - Finding the bugs in the unproved parts of a checked compiler is a documented pattern [9, 10, 11]. Two 2026 single-author arXiv preprints describe the same pattern in a compiler built by an AI agent [37, 38]. Neither has been peer reviewed.
- **What may be new is narrow.** This is as of 2026-11-02: the sweeps found nothing closer, but several competing preprints are still being revised.
  1. A plan checker that uses exact fixed-width integer semantics and proves every arithmetic step free of overflow. Exo and ATL treat values as real numbers, so they cannot state this property.
  2. That checker aimed at plans written by AI agents for integer CPU kernels, including multithreaded ones.
  3. Moving the exactness condition for `vpmaddubsw` *into that checker*, backed by an input contract that is enforced at run time (F3). Pitchfork formally verifies its lifting rules but leaves its lowering rules unverified ("future work"). Mainstream Halide and LLVM do not choose `pmaddubsw` for plain (non-saturating) sums from range facts. Halide's x86 backend does use range facts to select the related `pmaddwd` when a u8×i8 pair sum provably narrows to i16 [48]. The claim is about `pmaddubsw` specifically, not about range-based selection in general.
- **Point 3 is not true yet.** Today the `vpmaddubsw` rule lives in the emitter, where it is tested, not proved. The checker is unverified Python. Its equivalence check is structural only ("No algebra is used", `docs/superpowers/specs/2026-10-19-scale-design.md:81`).
- **What publication is realistic:**
  - **Now:** a 2-page extended abstract at a workshop such as ARRAY, or a student preprint.
  - **After the gaps in section 4:** a 12-page ARRAY workshop paper or an arXiv preprint. ARRAY is the best fit.
  - **Not realistic this cycle:** a main-track PLDI, CGO or ASPLOS paper. That would need a machine-checked checker and a much broader evaluation.

---

## 2. Novelty map

Verdicts are as of 2026-11-02.

| # | Finding | Closest prior work | What beryl adds | Verdict |
|---|---|---|---|---|
| F1 | Every serious bug found by the external review and the audit was in the trusted, unproved emitter or runtime. None was in the checker. | Csmith found CompCert's bugs only in its unproved parts [9]. Monniaux & Boulmé report that none of the problems found were in the verified parts, and most were in the code that expands and prints assembly [10]. Fonseca et al. found 16 bugs, all at the boundary between verified and unverified parts [11]. Rinard's Axon is a compiler built by an AI agent; its defects were in the printer, parser and machine model. Both Axon sources are 2026 arXiv preprints, and [38] has not been peer reviewed [37, 38]. | Two angles not found in prior work. (a) Text in the plan metadata (the plan ID) reached the C output without passing the checker, a textbook code injection (CWE-94 [46]). (b) The emitter redoes range reasoning the checker never proved: the block-length bug, and the `vpmaddubsw` condition (F2). | **Known pattern; worth reporting as a small case study.** The evidence is weak: about 5 bugs, found by reviews that deliberately looked at the emitter side, and the checker has never been searched for bugs as hard. Unproved checkers do fail: the eBPF verifier [13], Halide's simplifier [2]. |
| F2 | Use `vpmaddubsw` only when the declared ranges prove the pair sum fits in i16. Without that bound, the result is about half the right answer (5,107,068 vs 9,715,500). | The bound itself is long-standing practice: the Intel SDM [19], oneDNN's "u7" advice [20], PyTorch's `reduce_range` (now deprecated in favour of `quant_min`/`quant_max`) [21], ONNX Runtime's 7-bit weights [22], Jacob et al. [24] and FBGEMM [25]. WebAssembly relaxed SIMD restricts the second dot-product operand to 7 bits and leaves high-bit lanes implementation-defined [23], but it does not name `pmaddubsw` as the reason. Choosing an instruction from range facts: Pitchfork [17] and Rake [18]. An LLVM patch dropped its proposed PMADDUBSW matching during review because of this saturation hazard; only the PMADDWD part was committed [26a]. As of D49829 (2018), LLVM matches PMADDUBSW only on an explicit saturating clamp [26b]; check current `X86ISelLowering.cpp` before saying this is still true. | The condition is derived per program from declared, enforced ranges, not set by convention. Halide's x86 backend [48] maps `pmaddubsw` only to saturating dot products. It uses range facts to pick `pmaddwd`, not `pmaddubsw`, for plain u8×i8 pair sums. The checker-proved version is still a gap to close. | **Partly new**, and only once the rule is in the checker. Until then it is a known technique placed in the emitter. |
| F3 | Fused input validation: the output is unspecified on rejection, each block computes before checking, the status gives the exact first bad index, and arithmetic wraps to avoid undefined behaviour. Overhead is at most 2% on 4 threads and 5–9% on 1 thread. | The sweeps did not search for this specifically. The overflow-before-rejection bugs match Fonseca et al.'s "mismatched assumptions" class [11]. | It makes F2's premise true at run time: the declared ranges are checked, not assumed. Pitchfork gets its ranges from Halide's interval bounds inference over the expression, including constants and clamps. Rake proves bounds with SMT during synthesis. Neither takes ranges from an input contract enforced at run time. | **Not yet assessed.** Present it as a supporting mechanism, not a contribution, until a dedicated related-work search is done. |
| F4 | Benchmarking lessons: unequal output widths and compiler flags; `torch._int_mm` is an unoptimized CPU fallback; ratios that pair extremes from different runs; spinning thread pools inflating variance. | The sweeps confirmed no papers on benchmarking methodology. | Specific corrections for int8 CPU comparisons. | **Known kind of lesson, not a contribution.** Use it as the methodology section. Do not claim it. |
| F5 | AI agents write the code and propose plans; a proof gate decides what runs. | STOKE [32], CryptOpt [33], LLM-Vectorizer [30], LLMLift [31], ComPilot [34] (weaker: legality check plus speedup, no equivalence proof), Volta [35] and ProofWright [36] (both arXiv preprints), Axon [37] (preprint). KernelBench [39], a refereed benchmark, shows that AI-written kernels are often wrong. Several preprints report more failures or harnesses that accept wrong kernels [40, 41, 42]. | A gate that is exact for integers, checks over symbolic sizes, and receives small structured plans rather than arbitrary C. Volta's abstract claims soundness, and completeness for a class of kernels [35]. ProofWright's abstract claims memory safety, thread safety and semantic correctness [36]. Neither abstract settles whether they handle symbolic shapes or fixed-width overflow, so cite specific sections of the current versions (Volta v3, ProofWright v2) before stating a difference. LLM-Vectorizer verifies with Alive2, a bounded translation validator [28]. One verification pass reports that it checks loops unrolled a fixed number of times, with trip counts a multiple of the vector width [30]; confirm this in the paper before stating it. | **Partly new as a combination**, as of 2026-11-02. It becomes measurable only with plan-rejection statistics (Gap 4). |

---

## 3. The paper to write

### Recommended framing

Lead with the strongest point that can actually be proved: **range facts belong in the checker.** A checker-gated compiler for AI-proposed integer kernels should prove every range fact that code generation depends on. That covers freedom from overflow, and also the exactness conditions of saturating SIMD instructions.

- F1 is the motivation: the bugs appeared where the emitter repeated range reasoning outside the checker.
- F2 is the worked example, moved into the checker.
- F3 is why the premise holds at run time.
- F5 is the setting, not a claim.
- F4 goes into the methodology section.

### Working title

*Range Facts Belong in the Checker: Overflow-Exact Plan Checking and Saturating-SIMD Selection for Agent-Proposed Integer Kernels*

### Sample abstract (about 150 words)

**This is a model to study, not text to submit.** It describes the state *after* Gaps 1–3 are done. Each bracketed part is false until its gap is closed; drop it if the gap is not closed.

> beryl is a compiler for integer array kernels written as per-cell formulas over inputs with declared integer ranges. Untrusted planners, including AI coding agents, propose loop plans, and a separate checker decides what runs. The checker accepts a plan only if it shows, for symbolic sizes, that the plan matches the formula, stays in bounds, and cannot overflow in fixed-width integer arithmetic. The checker is Python with a [written, not mechanized,] soundness argument; the C emitter and thread pool are trusted but not proved. Of the serious bugs found by an external review and an audit, none was in the checker (which was tested less hard), and one came from the emitter redoing range reasoning outside it. [I move one such rule, the exactness condition for the saturating AVX2 instruction vpmaddubsw, into the checker.] With it, an int8 dense layer matches PyTorch/FBGEMM on one thread and runs 1.08–1.42x faster on four threads of one Zen 2 CPU.

### Section outline: what each section must show

1. **Introduction.**
   - Show that the problem is real. Rest this mainly on KernelBench [39]: AI-written kernels are often wrong. Add the preprints [41, 42] as further reports, labelled as preprints, including the report that test harnesses can be gamed.
   - List two or three narrow contributions.
   - Say explicitly what is *not* new: the validator pattern, size-independent checking, and the bound itself.
2. **Background.**
   - `vpmaddubsw` semantics from the SDM [19].
   - The pair bound, and how libraries handle it by convention [20, 21, 24, 25].
   - A small example in which saturation silently halves the result.
3. **Design and trust boundary.**
   - The formula language and the plan language.
   - One table with a row per component (checker, emitter, thread pool, clang), marked proved, argued, or tested. Reviewers will look for this table first.
4. **The checker.**
   - Each proof obligation: equivalence, bounds, and overflow per arithmetic node.
   - How intervals are computed over fixed-width types and symbolic sizes.
   - A worked example with real step counts (49 steps at 20×20 and at 2000×2000), presented as expected behaviour, not as a headline.
   - What the checker rejects because equivalence is structural only.
   - The soundness argument, in an appendix.
5. **Range side conditions for instruction selection.**
   - The `vpmaddubsw` obligation using the **tight** bound: 2·u_max·w_min ≥ −32768 and 2·u_max·w_max ≤ 32767, assuming u_min ≥ 0.
   - A proof of the lemma "within these intervals, saturation never fires".
   - How the run-time input contract (F3) establishes the premise.
   - Negative tests: plans and ranges that must be rejected.
6. **Where the bugs were (case study).**
   - Each bug with its cause, its class and its precedent [9, 10, 11, 46].
   - Threats to validity: about five bugs, reviewers aimed at the emitter, and no comparable search of the checker.
7. **Evaluation.**
   - Performance against PyTorch/FBGEMM with and without `reduce_range`, oneDNN and Halide, on two machines.
   - Plan statistics from AI agents: how many were rejected, why, and whether random-input tests would have caught each one.
   - A seeded-mutation catch rate.
   - Checking time.
   - Methodology (F4): medians and spreads, and no ratios that pair extremes from different runs.
8. **Related work.** Organize it around the novelty map in section 2.
9. **Limitations.**
   - The checker is not mechanized.
   - The equivalence check is structural only.
   - The emitter, thread pool and clang are trusted.
   - Integers only, CPU only, a single ISA family.
10. **AI-use statement.** See section 6.

---

## 4. Gaps to close before submitting

Effort figures assume part-time work by a student who understands each step, not delegating to an AI.

| # | Work item | Effort | Why reviewers need it |
|---|---|---|---|
| 1 | **Move the `vpmaddubsw` rule into the checker** as a proof obligation, using the tight bound. Add negative tests that the checker rejects. | 1–2 weeks | Without this, F2 says "range-proved" when it is really "tested". The current rule refuses `0..=128` with weights `-128..=127` only because it is conservative: the real pair range is [−32768, 32512], which fits in i16. Fix the wording that implies otherwise: `docs/pitch/medici-loom-script.md` lines 30, 101 and 110, `docs/reviews/2026-10-25-matched-benchmarks.md:333`, and the assertion in `tools/test_showcase.py:276` that checks that text. |
| 2 | **A written soundness argument for the template proofs.** Define what a plan means, then argue rule by rule that acceptance implies equal results, in-bounds access and no overflow, for all sizes. Write it yourself. | 3–6 weeks | It is the paper's central claim. Reviewers will compare it with ATL and Fiat, which are proved in Coq [6, 16]. A careful paper proof is the minimum. |
| 3 | **Optionally, mechanize the pair-bound lemma** in Lean or Coq. Only the lemma, not the whole checker. | 2–4 weeks, including learning the tool | It turns "partly new" into something reviewers can trust, and it is small enough to finish. |
| 4 | **Plan statistics from AI agents:** run agents as planners on a set of kernels, then log every rejection, its reason, and whether a test on a few random inputs would have caught it. | 1–2 weeks | This is the only measurable evidence for F5. It answers "why not just test?" [39]; see also the preprint [41]. |
| 5 | **Try to break the checker:** hand-made unsound plans, seeded plan mutations, and mutations of the checker code itself. Report the catch rate. | 1–2 weeks | F1's "no bugs in the checker" means little until the checker has been tested as hard as the emitter [13, 2]. |
| 6 | **Check the `beryl_dot_u8i8` helper itself:** an SMT check on fixed-width values (Z3) that it equals the scalar sum, including the int32 partial sums and the scalar tail. | 1–2 weeks | It closes the emitter gap for the one helper the headline result depends on (compare Alive2 [28] and Crocus [29]). |
| 7 | **A second machine:** an Intel AVX2 machine, ideally also one with VNNI (`vpdpbusd`). | Days, once you have the hardware (a cloud VM works) | One Ryzen 3 3100 is not enough to generalize performance claims. |
| 8 | **Baselines:** Halide on the same plain-sum dense layer, oneDNN, and PyTorch/FBGEMM with and without `reduce_range`. Match output widths and compiler flags. For Halide, record which instruction it actually emits; per [48] it should not use `pmaddubsw`, and it may use `pmaddwd`. | 2–3 weeks | It shows a case the closest prior systems do not handle the same way, and it removes the baseline problems found in F4. |
| 9 | **Benchmark hygiene:** pinned threads, many repetitions, medians with spread, and every run reported. Check how 1.08–1.42x was computed. | Days | F4 already found that ratios pairing extremes across runs can mislead. |
| 10 | **Fix unconfirmed external claims** in `docs/superpowers/specs/2026-10-25-ml-scale-cpu-core-design.md` lines 62–66. "ONNX Runtime added a checker" is unconfirmed. "Hand-written libraries cannot do this safely" should become "they do it safely by convention, not per program". | Hours | A reviewer who knows oneDNN or ONNX Runtime will catch both. |
| 11 | **A reproducible package:** scripts, pinned versions, one command per table. | About 1 week | Workshops increasingly expect it, and it backs every number in the paper. |
| 12 | **An outside reader:** a professor or graduate student in programming languages or compilers who reads the draft. This person can also endorse you on arXiv. | Ongoing | arXiv requires an endorser (section 5), and an outside reader is the best check on the claims. |
| 13 | **A related-work search for F3** (fused validation with a first-bad-index status). | Hours to days | Do it before saying anything about whether F3 is new. |
| 14 | **Re-check the fast-moving related work** (Volta, ProofWright, Axon, LLM-Vectorizer) against their latest versions, and cite specific sections for each comparison in F5. | Days | The F5 comparisons currently rest on abstracts, and several of these papers were revised in 2026. |

Minimum for a 2-page extended abstract: items 1, 9 and 10. Minimum for a 12-page workshop paper: items 1, 2, 4, 5, 7, 8, 9, 10 and 14.

---

## 5. Where to send it

These are in order of fit. "Unconfirmed" means the verification could not find it on an official page.

1. **ARRAY at PLDI 2027.** This is the best fit: its 2026 call covers correctness, formal verification and static analysis of array programs, and SIMD targets.
   - Format, based on 2026: a 12-page full paper in the ACM Digital Library, or a 2-page extended abstract that is "lightly reviewed" and not in the Digital Library.
   - Affiliation and cost are **unconfirmed**: the ARRAY 2026 page does not say whether an affiliation is needed or who pays registration and travel. Ask the organizers.
   - The 2027 call is not out. In 2026 the deadline was Apr 6 and the workshop was on Jun 16. PLDI 2027 is Jun 5–11 in Atlanta.
2. **arXiv preprint** in cs.PL, cross-listed to cs.PF, when the paper is ready, possibly before ARRAY.
   - You need a **personal endorser**. arXiv's blog post of Jan 21, 2026 says an institutional email alone no longer qualifies.
   - Significant use of generative AI for text must be reported, and AI cannot be listed as an author.
   - Each author may make at most 2 new submissions per calendar month (3 active).
   - Check every reference by hand. News reports describe a one-year ban for unchecked AI content, but arXiv's own pages do not state it.
3. **SOAP at PLDI 2027.** It takes preliminary work, which suits the checker. The 2026 deadline was Mar 10 (extended from Mar 3). The 2027 dates are not posted.
4. **C4ML at CGO 2027.** A good fit for the int8 / `vpmaddubsw` result. CGO 2027 is Mar 20–24, 2027 in Salt Lake City, according to the 2027.cgo.org pages. C4ML 2027 itself is **unconfirmed**.
5. **Regeneron ISEF 2027,** reached through your affiliated regional fair (find it at findafair.societyforscience.org).
   - Software Design (SFTD) is one of the 2027 categories.
   - Society for Science web pages give ISEF 2027 as May 8–14, 2027 in Los Angeles; the rules book itself does not give the dates. **Your regional fair's deadline is not confirmed here.**
   - Eligibility: no research performed before January 2026, and at most 12 continuous months of work ending May 2027. The first commit (2026-10-17) is inside this window.
   - You must write your own research plan, abstract and poster. AI may not write those or generate the citations.
   - Rule 8 covers all generative AI use, not only code. AI may be used as a project resource, but it must be cited and acknowledged. The research plan must document AI support "with a prompt log or an explanation". The AI Usage Disclosure asks for a prompt log, or a summary if the log is not available.
   - The research plan is supposed to come before experimentation, so ask your fair how it handles work already done.
6. **ACM/CSTA Cutler-Bell Prize.** It is open to high-school seniors planning to study computer science. You submit a video and essays, plus source code in the Intermediate and Advanced tiers. **2026–27 dates are not posted.** Its AI rules are not stated.
7. **NHSJS.** AI-written code is allowed if disclosed, but all prose must be your own, with no AI drafting, paraphrasing or translation. The median time to a first decision is about 8 weeks, and 95% of decisions come within 14 weeks. Standard review lists no fee, and each Fast Track option costs $280. A non-refundable article processing charge is mentioned, but its amount is **unconfirmed**, as are whether NHSJS takes computer science and its rules on mentors.
8. **Regeneron STS 2027.** Due **Thursday, Nov 5, 2026, 8 PM ET** (in three days), recommendations included. Customer support closes Nov 4 at 8 PM ET.
   - The research report is limited to 20 pages. Generative AI may not write application answers, draft the report or generate citations.
   - My advice: **enter only if the report, recommenders and transcript are already mostly done.** Otherwise skip it. Skipping costs nothing except this year's chance; that is a judgement, not an official rule.

**Not eligible:**

- **JEI.** It excludes computer science, and manuscripts that only introduce, optimize or compare a method or algorithm.
- **ACM Student Research Competitions** (for example POPL 2027 SRC). Only enrolled undergraduate and graduate students who are ACM student members may enter. This becomes possible from fall 2027 if you are enrolled at a university and join ACM.

---

## 6. Owning the work

The rules for STS, ISEF and NHSJS, and ordinary honesty, require that you can defend every claim yourself. The core fact is that AI agents wrote most of the code and made many of the design decisions.

### Re-derive by hand, on paper, without notes

1. **The pair bound.**
   - Compute the pair-sum range for `0..=127`, `0..=128` and `0..=255` against `-128..=127`.
   - Explain why the tight bound accepts 128 and the current rule does not.
   - Explain why 5,107,068 comes out instead of 9,715,500.
2. **Interval arithmetic.**
   - The rules for +, −, ×, and a sum over a symbolic range, in fixed-width types.
   - Why the sign of a range matters for ×.
3. **One full check.** Run the checker on a small plan (for example the 20×20 case) and follow every one of the 49 steps, saying what each one proves. Then explain why 2000×2000 takes the same number of steps.
4. **Each F1 bug.** For each one: the cause, why the checker could not catch it, the fix, and the class it belongs to (section 2).
5. **F3.** Why computing before validating forces wrapping arithmetic, and what "output unspecified on rejection" does and does not promise.

### Read before writing

Use the list in section 7. For each paper, write a three-sentence summary in your own words: what it proves, what it trusts, and how beryl differs.

### Explain without notes

You should be able to answer each of these questions, as an interviewer or reviewer might ask them:

- "How is this different from CompCert's validators, Exo and Pitchfork?"
- "What does the checker *not* prove?"
- "Why should I believe the checker is correct?"
- "Which parts did you decide, and which did the AI decide?"

### Write it yourself

- Write the paper, the research plan, the abstract and any essays yourself, from your own notes. Do not reuse the AI-written specs and reviews in the repository as text.
- Use AI for light grammar edits only where the venue allows it, and credit it. NHSJS does not allow it for prose at all.
- Keep a decision log: for each major design choice, record who proposed it and whether you can now justify it. Claim as yours only what you can defend.

### Describe AI's role truthfully

The statement goes in the Acknowledgements or in a separate AI-use section, as each venue requires.

- Name Claude and Codex.
- Say what they did:
  - wrote most of the implementation;
  - proposed plans;
  - made or suggested many design decisions;
  - drafted the specs;
  - carried out the external review.
- Say what you did. For example:
  - posed the question;
  - set the trust boundary;
  - chose what to measure;
  - judged which claims survived;
  - wrote the paper.
- For ISEF, export the Claude and Codex transcripts as the prompt log the AI Usage Disclosure asks for, or give a summary where a log is missing, and mark which code was AI-generated. For STS, check the AI Usage Chart for what it requires.
- AI is never an author.
- Note that the subject of the paper (a proof gate that does not trust AI output) is consistent with this history, but it does not replace the disclosure.

---

## 7. Reading list, in learning order

1. **Intel SDM, PMADDUBSW [19], and oneDNN "Nuances of int8 Computations" [20].** The exact instruction semantics, and how practitioners work around them.
2. **Jacob et al. 2018 [24].** The clearest published version of the argument that products fit, so pairs can share a narrow accumulator.
3. **Halide, PLDI 2013 [1].** The algorithm/schedule split and the interval bounds inference that beryl's design builds on.
4. **Leroy, CACM 2009 [7].** Why an unverified optimizer plus a verified validator is as strong as a verified compiler. This is beryl's design, done rigorously.
5. **Tristan & Leroy, POPL 2008 [8].** The closest precedent for an untrusted scheduler plus a checker that decides.
6. **Fiat Cryptography, S&P 2019 [16], section IV.** Interval bounds inference with a Coq proof: the standard to compare beryl's overflow proofs against.
7. **Exo, PLDI 2022 [5].** The closest checked scheduling system. Note that it treats values as real numbers and does not model parallelism.
8. **ATL, POPL 2022 [6].** Coq-verified rewrites with a trusted lowering to C: the same split as beryl, but machine-checked.
9. **Pitchfork, ASPLOS '23 Vol. 4 [17].** Range-predicated lowering of saturating instructions. This is the paper you most need to distinguish F2 from.
10. **Yang et al., Csmith, PLDI 2011 [9].** The original evidence that the bugs in a verified compiler live in its unproved parts.
11. **Monniaux & Boulmé, ESOP 2022 [10].** The best account of what a verified compiler still trusts. It maps directly onto beryl's emitter.
12. **Fonseca et al., EuroSys 2017 [11].** The "mismatched assumptions" taxonomy for beryl's concurrency and overflow-before-rejection bugs.
13. **Rinard, Axon, arXiv:2605.01660, 2026 [37].** A recent example of an AI-agent-built checked compiler, and a model for how to disclose AI authorship. It is a preprint. A talk with the same title appears in a third-party listing of the PAgE '26 program, which has not been confirmed on the official PLDI 2026 site.
14. **LLM-Vectorizer, CGO 2025 [30], with Alive2, PLDI 2021 [28].** The CPU-SIMD "LLM proposes, verifier decides" system beryl must be compared with, and its bounded checking.
15. **KernelBench, ICML 2025 [39].** Why tests alone are not enough for AI-written kernels. Optionally add Shah & Shrestha 2026 [41], which is not peer reviewed.

---

## 8. References

1. J. Ragan-Kelley, C. Barnes, A. Adams, S. Paris, F. Durand, S. Amarasinghe. "Halide: a language and compiler for optimizing parallelism, locality, and recomputation in image processing pipelines." PLDI 2013. https://people.csail.mit.edu/jrk/halide-pldi13.pdf
2. J. Newcomb, A. Adams, S. Johnson, R. Bodík, S. Kamil. "Verifying and Improving Halide's Term Rewriting System with Program Synthesis." PACMPL 4 (OOPSLA), 2020. https://doi.org/10.1145/3428234 (PDF: https://inst.eecs.berkeley.edu/~cs294-260/sp24/papers/verifying-halide-trs.pdf)
3. T. Chen et al. "TVM: An Automated End-to-End Optimizing Compiler for Deep Learning." OSDI 2018. https://www.usenix.org/conference/osdi18/presentation/chen
4. Y. Ikarashi, J. Qian, Y. Droubi, A. Reinking, G. Bernstein, J. Ragan-Kelley. "Exo 2: Growing a Scheduling Language." ASPLOS 2025. https://arxiv.org/abs/2411.07211
5. Y. Ikarashi, G. L. Bernstein, A. Reinking, H. Genc, J. Ragan-Kelley. "Exocompilation for Productive Programming of Hardware Accelerators." PLDI 2022. https://par.nsf.gov/servlets/purl/10342192
6. A. Liu, G. Bernstein, A. Chlipala, J. Ragan-Kelley. "Verified Tensor-Program Optimization Via High-Level Scheduling Rewrites." PACMPL 6 (POPL), 2022. https://adam.chlipala.net/papers/AtlPOPL22/
7. X. Leroy. "Formal Verification of a Realistic Compiler." CACM 52(7), 2009. https://xavierleroy.org/publi/compcert-CACM.pdf
8. J.-B. Tristan, X. Leroy. "Formal verification of translation validators: a case study on instruction scheduling optimizations." POPL 2008. https://xavierleroy.org/bibrefs/Tristan-Leroy-scheduling.html
9. X. Yang, Y. Chen, E. Eide, J. Regehr. "Finding and Understanding Bugs in C Compilers." PLDI 2011. https://www-old.cs.utah.edu/~regehr/papers/pldi11-preprint.pdf
10. D. Monniaux, S. Boulmé. "The Trusted Computing Base of the CompCert Verified Compiler." ESOP 2022. https://arxiv.org/abs/2201.10280
11. P. Fonseca, K. Zhang, X. Wang, A. Krishnamurthy. "An Empirical Study on the Correctness of Formally Verified Distributed Systems." EuroSys 2017. https://www.cs.purdue.edu/homes/pfonseca/papers/eurosys2017-dsbugs.pdf
12. C. Courant, X. Leroy. "Verified code generation for the polyhedral model." PACMPL 5 (POPL), 2021. https://xavierleroy.org/bibrefs/Courant-Leroy-polygen.html
13. H. Vishwanathan, M. Shachnai, S. Narayana, S. Nagarakatte. "Verifying the Verifier: eBPF Range Analysis Verification." CAV 2023. https://par.nsf.gov/biblio/10467089
14. G. C. Necula. "Proof-Carrying Code." POPL 1997. https://bibtex.github.io/POPL-1997-Necula.html (PDF: https://courses.grainger.illinois.edu/cs421/fa2010/papers/necula-pcc.pdf)
15. A. Pnueli, M. Siegel, E. Singerman. "Translation Validation." TACAS 1998. https://bibtex.github.io/TACAS-1998-PnueliSS.html
16. A. Erbsen, J. Philipoom, J. Gross, R. Sloan, A. Chlipala. "Simple High-Level Code For Cryptographic Arithmetic – With Proofs, Without Compromises." IEEE S&P 2019. https://adam.chlipala.net/papers/FiatCryptoSP19/
17. A. Root, M. B. S. Ahmad, D. Sharlet, A. Adams, S. Kamil, J. Ragan-Kelley. "Fast Instruction Selection for Fast Digital Signal Processing" (Pitchfork). ASPLOS '23, Vol. 4 (published 2024, presented at ASPLOS 2024). DOI 10.1145/3623278.3624768. https://par.nsf.gov/servlets/purl/10518966
18. M. B. S. Ahmad, A. Root, A. Adams, S. Kamil, A. Cheung. "Vector Instruction Selection for Digital Signal Processors using Program Synthesis" (Rake). ASPLOS 2022. https://maaz139.github.io/papers/asplos22.pdf
19. Intel 64 and IA-32 Architectures SDM, PMADDUBSW (unofficial mirror). https://www.felixcloutier.com/x86/pmaddubsw
20. oneDNN Developer Guide, "Nuances of int8 Computations." https://uxlfoundation.github.io/oneDNN/dev_guide_int8_computations.html
21. PyTorch, `torch/ao/quantization/observer.py` (`reduce_range`, now deprecated in favour of `quant_min`/`quant_max`). Main branch, accessed 2026-11-02; pin a commit hash before publishing. https://raw.githubusercontent.com/pytorch/pytorch/main/torch/ao/quantization/observer.py
22. ONNX Runtime, "Quantize ONNX models." https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html
23. WebAssembly Relaxed SIMD proposal, Overview. https://github.com/WebAssembly/relaxed-simd/blob/main/proposals/relaxed-simd/Overview.md
24. B. Jacob et al. "Quantization and Training of Neural Networks for Efficient Integer-Arithmetic-Only Inference." CVPR 2018. https://arxiv.org/abs/1712.05877
25. D. Khudia et al. "FBGEMM: Enabling High-Performance Low-Precision Deep Learning Inference." arXiv:2101.05615, 2021. https://arxiv.org/abs/2101.05615
26. LLVM reviews:
    - (a) D. Chen (danielcdh). "Use PMADDWD to expand reduction in a loop." D31679, 2017; committed as rL299776, April 2017. Proposed PMADDUBSW matching was dropped during review. https://reviews.llvm.org/D31679
    - (b) C. Topper. "[X86] Add pattern matching for PMADDUBSW." D49829, 2018; committed as rL338402, July 31, 2018. https://reviews.llvm.org/D49829
27. I. Colbert, A. Pappalardo, J. Petri-Koenig. "A2Q: Accumulator-Aware Quantization with Guaranteed Overflow Avoidance." ICCV 2023. https://arxiv.org/abs/2308.13504
28. N. P. Lopes, J. Lee, C.-K. Hur, Z. Liu, J. Regehr. "Alive2: Bounded Translation Validation for LLVM." PLDI 2021. https://www-old.cs.utah.edu/~regehr/alive2-pldi21.pdf
29. A. VanHattum, M. Pardeshi, C. Fallin, A. Sampson, F. Brown. "Lightweight, Modular Verification for WebAssembly-to-Native Instruction Selection." ASPLOS 2024. https://par.nsf.gov/biblio/10546563-lightweight-modular-verification-webassembly-native-instruction-selection
30. J. Taneja, A. Laird, C. Yan, M. Musuvathi, S. K. Lahiri. "LLM-Vectorizer: LLM-based Verified Loop Vectorizer." CGO 2025. https://arxiv.org/abs/2406.04693
31. S. Bhatia, J. Qiu, N. Hasabnis, S. Seshia, A. Cheung. "Verified Code Transpilation with LLMs." NeurIPS 2024. https://neurips.cc/virtual/2024/poster/93370
32. E. Schkufza, R. Sharma, A. Aiken. "Stochastic Superoptimization." ASPLOS 2013. https://arxiv.org/abs/1211.0557
33. J. Kuepper, A. Erbsen, J. Gross, O. Conoly, C. Sun, S. Tian, D. Wu, A. Chlipala, C. Chuengsatiansup, D. Genkin, M. Wagner, Y. Yarom. "CryptOpt: Verified Compilation with Randomized Program Search for Cryptographic Primitives." PACMPL 7 (PLDI), 2023, article 158. DOI 10.1145/3591272. https://doi.org/10.1145/3591272 (the authors' page, https://adam.chlipala.net/papers/CryptoptPLDI23/, says "Random" instead of "Randomized"; use the DOI title)
34. M. Merouani, I. Kara Bernou, R. Baghdadi. "Agentic Auto-Scheduling: An Experimental Study of LLM-Guided Loop Optimization." PACT 2025. https://arxiv.org/abs/2511.00592
35. B. Driscoll, K. Dubey, A. Wei, N. Kayal, R. Sharma, A. Aiken. "Equivalence Checking of ML GPU Kernels." arXiv:2511.12638, 2025 (v3 Aug 2026; preprint, no venue). https://arxiv.org/abs/2511.12638
36. B. Chatterjee, D. Zagieboylo, S. Damani, S. Hari, C. Kozyrakis. "ProofWright: Towards Agentic Formal Verification of CUDA." arXiv:2511.12294, 2025 (v2 Mar 2026; preprint, no venue). https://arxiv.org/abs/2511.12294
37. M. Rinard. "Testing, Credible Compilation, and Verification in the Axon Verified Compiler in Lean and Claude Code." arXiv:2605.01660, 2026 (v3 Jul 2026; preprint). A talk with this title appears in a third-party listing of the PAgE '26 program at PLDI 2026; confirm it on pldi26.sigplan.org before citing it as a workshop paper. https://arxiv.org/abs/2605.01660
38. M. Rinard. "Automated Testing and Repair for Verified Compilers Generated by a Coding Agent." arXiv:2607.28928, 2026 (preprint, not peer reviewed). https://arxiv.org/abs/2607.28928
39. A. Ouyang, S. Guo, S. Arora, A. L. Zhang, W. Hu, C. Ré, A. Mirhoseini. "KernelBench: Can LLMs Write Efficient GPU Kernels?" ICML 2025, PMLR 267, pp. 47356–47415. https://proceedings.mlr.press/v267/ouyang25a.html
40. H. Wang, J. Zhang, K. Jiang, H. Wang, J. Chen, J. Zhu. "KernelBenchX: A Comprehensive Benchmark for Evaluating LLM-Generated GPU Kernels." arXiv:2605.04956, 2026 (preprint). https://arxiv.org/abs/2605.04956
41. R. Shah, R. Shrestha. "A Contract-Grade Verifier for LLM-Generated GPU Kernels, and a Native Blackwell Backward for the Gated-Linear-Recurrence Family." arXiv:2608.12700, 2026 (not peer reviewed). https://arxiv.org/abs/2608.12700
42. C. Baronio, P. Marsella, B. Pan, S. Guo, S. Alberti. "Kevin: Multi-Turn RL for Generating CUDA Kernels." arXiv:2507.11948, 2025 (preprint). https://arxiv.org/abs/2507.11948
43. J. Arora et al. "TensorRight: Automated Verification of Tensor Graph Rewrites." POPL 2025. https://popl25.sigplan.org/details/POPL-2025-popl-research-papers/29/TensorRight-Automated-Verification-of-Tensor-Graph-Rewrites
44. X. Li, H. Liang, X. Feng. "Verified Validation for Affine Scheduling in Polyhedral Compilation." TASE 2024, pp. 287–305. https://plax-lab.github.io/publications/polyhedral/index.html
45. T. Sewell, M. Myreen, G. Klein. "Translation Validation for a Verified OS Kernel." PLDI 2013, pp. 471–481. https://trustworthy.systems/publications/nictaabstracts/Sewell_MK_13.abstract
46. MITRE. "CWE-94: Improper Control of Generation of Code." CWE version 5.0 (version 4.x titled it "... ('Code Injection')"). https://cwe.mitre.org/data/definitions/94.html
47. M. Nahar, S. Lee, R. Guillen, D. Lee. "Generative AI Policies under the Microscope: How CS Conferences Are Navigating the New Frontier in Scholarly Writing." arXiv:2410.11977, 2024; to appear in Communications of the ACM, 2025 (cite the CACM version if it has been published). https://arxiv.org/abs/2410.11977
48. Halide source, `src/CodeGen_X86.cpp`. Main branch, accessed 2026-11-02; pin a commit hash before publishing, because the file changes. https://raw.githubusercontent.com/halide/Halide/main/src/CodeGen_X86.cpp

**Venue sources.** These were checked by the verification pass; the items in section 5 marked unconfirmed are exactly the ones these pages do not support.
- STS rules: https://sspcdn.blob.core.windows.net/files/Documents/SEP/STS/2027/Application/Official-Rules.pdf
- STS AI usage chart: https://sspcdn.blob.core.windows.net/files/Documents/SEP/STS/2027/Application/AI-Usage-Chart.pdf
- ISEF rules (2026–2027 International Rules): https://sspcdn.blob.core.windows.net/files/Documents/SEP/ISEF/2027/Rules/Book.pdf (the ISEF 2027 dates come from Society for Science web pages, not this book)
- ARRAY 2026: https://pldi26.sigplan.org/home/ARRAY-2026
- SOAP 2026: https://pldi26.sigplan.org/home/SOAP-2026
- PLDI 2027: https://pldi27.sigplan.org/
- CGO 2027: https://2027.cgo.org/
- arXiv endorsement change: https://blog.arxiv.org/2026/01/21/attention-authors-updated-endorsement-policy/ (help page: https://info.arxiv.org/help/endorsement.html)
- NHSJS AI policy: https://nhsjs.com/ai-usage-policy/
- NHSJS review times and fees: https://nhsjs.com/?p=22
- Cutler-Bell Prize: https://csteachers.org/awards/cutlerbell/
- JEI scope: https://emerginginvestigators.org/submissions/hypothesis-driven-research
- POPL 2027 SRC: https://popl27.sigplan.org/track/POPL-2027-student-research-competition

No repository files were edited. Files cited from the repo:
- C:/Users/moham/Desktop/beryl/.local-workspaces/BerylLattice/axiom/src/axiom/scale_checker.py
- C:/Users/moham/Desktop/beryl/.local-workspaces/BerylLattice/docs/pitch/medici-loom-script.md (lines 30, 101, 110)
- C:/Users/moham/Desktop/beryl/.local-workspaces/BerylLattice/docs/reviews/2026-10-25-matched-benchmarks.md (line 333)
- C:/Users/moham/Desktop/beryl/.local-workspaces/BerylLattice/tools/test_showcase.py (line 276)
- C:/Users/moham/Desktop/beryl/.local-workspaces/BerylLattice/docs/superpowers/specs/2026-10-25-ml-scale-cpu-core-design.md (lines 62–66)
- C:/Users/moham/Desktop/beryl/.local-workspaces/BerylLattice/docs/superpowers/specs/2026-10-19-scale-design.md (line 81)

---

## Verification note

Three passes checked 49 reference entries (refs 1–48, with ref 26 split into 26a and 26b) and all the venue claims. All 49 references exist, so none were removed.

**Wrong details, now fixed (2):**
- [40]: the title was truncated; the full title is now given.
- [46]: the CWE-94 title was outdated; it now uses the version 5.0 title and notes the version.

**Incomplete entries, now completed or annotated:**
- [17]: now cited as ASPLOS '23 Vol. 4, with its DOI.
- [20]: title capitalization fixed.
- [21]: notes that `reduce_range` is deprecated, plus a reminder to pin a commit.
- [26a]: author Dehao Chen and commit rL299776 added.
- [26b]: title and commit rL338402 added.
- [33]: DOI, all 12 authors, and a warning about the "Random" vs "Randomized" title mismatch.
- [35], [36]: year and preprint status added.
- [37]: now cited as an arXiv preprint; the PAgE '26 venue is marked unconfirmed.
- [38], [42]: marked as preprints.
- [47]: year and CACM status added.
- [48]: reminder to pin a commit.

**Claims changed in the text:**
- **Header:** the blanket "confirmed by a sweep" was replaced with an accurate description, and novelty verdicts are now dated 2026-11-02.
- **LLVM:** "removed PMADDUBSW support" became "a patch dropped proposed PMADDUBSW matching". The clamp-only matching is now scoped to "as of D49829 (2018)".
- **WebAssembly [23]:** now cited only as a typing restriction, not as stating the `pmaddubsw` pair bound.
- **Halide:** the plan now says Halide does use range facts to select `pmaddwd`, so "no range-based selection" cannot be read as the claim.
- **Pitchfork/Rake ranges:** the description in F3 is now precise.
- **ComPilot:** presented as a weaker form of the pattern.
- **Volta, ProofWright, LLM-Vectorizer:** the F5 comparisons were softened until specific sections are checked, and a new Gap 14 covers that check.
- **Axon:** the F1 precedent and the reading list now say these are preprints.
- **"Strong evidence":** removed; the claim now rests mainly on KernelBench [39].

**Venue fixes:**
- ARRAY: affiliation and cost marked unconfirmed.
- SOAP: Mar 10 noted as extended from Mar 3.
- CGO 2027: location and source added.
- ISEF: the AI rule now covers all generative AI and mentions the prompt log or summary; the exact eligibility window is added; the source of the dates is noted.
- Cutler-Bell: source code is required only in some tiers.
- NHSJS: the review-time range and the $280 Fast Track fee are added.
- arXiv: the blog post is now cited, and the per-month limit is stated precisely.
- STS: "no penalty" is labelled as advice; the AI rule for STS now points to its AI Usage Chart.
- ACM SRC: the enrollment and membership conditions are stated.

The structure of the plan is unchanged.