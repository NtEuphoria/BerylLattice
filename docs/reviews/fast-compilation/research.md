# Verified primary sources for Beryl cold compilation

Accessed 2026-10-18 UTC. Source URLs, redirect URLs, SHA-256 hashes, byte counts, and failed attempts are in [research-sources.json](research-sources.json). Original downloaded copies and text extractions remain under `/workspace/scratch/beryl-compile-research/literature`; papers are not vendored into this repository. The literature subtask performed no package installation or compiler timing tests. Separate compiler measurements are retained alongside these notes.

## Seven strongest sources

1. **Jonathan Ragan-Kelley, Connelly Barnes, Andrew Adams, Sylvain Paris, Frédo Durand, and Saman Amarasinghe. “Halide: A Language and Compiler for Optimizing Parallelism, Locality, and Recomputation in Image Processing Pipelines.” PLDI 2013.**
   - Primary PDF: https://people.csail.mit.edu/jrk/halide-pldi13.pdf
   - Verified against PDF title page, abstract, and introduction. The Halide project homepage links this author-hosted PDF; the initially supplied `halide-lang.org/papers/halide_pldi_2013.pdf` returns 404.
   - Published contribution: separate the algorithm from its execution schedule; represent choices over locality, parallelism, and recomputation; synthesize implementations from algorithm plus schedule. It also explores stochastic schedule search.
   - Beryl implication (our application): represent the finite relation/result definition once, and represent loop order, tile size, storage, and materialization as separate schedule data. Do not rebuild and expand the source semantics merely to compare schedules. Preserve structured loops until a schedule requires lowering them.
   - Limit: Halide is an image-pipeline system and its paper establishes runtime optimization benefits, not Beryl cold-compile speedups. Stochastic schedule search belongs outside a latency-critical default path.

2. **Chris Lattner, Mehdi Amini, Uday Bondhugula, Albert Cohen, Andy Davis, Jacques Pienaar, River Riddle, Tatiana Shpeisman, Nicolas Vasilache, and Oleksandr Zinenko. “MLIR: A Compiler Infrastructure for the End of Moore’s Law.” 2020 preprint, arXiv:2002.11054v2.**
   - Primary abstract/metadata: https://arxiv.org/abs/2002.11054
   - Primary PDF: https://arxiv.org/pdf/2002.11054
   - Verified sections 2 and 5.2: nested regions and SSA; preserve higher-level structure while useful; progressive lowering through multiple abstraction levels; affine maps and integer sets.
   - Beryl implication (our application): use a compact IR with `Domain`, `Filter`, `Map`, `Reduce`, structured loops, and explicit bounded integer semantics. Emit C/Wasm after selecting a schedule rather than expanding everything into one low-level straight-line representation early.
   - Limit: this is an architectural precedent, not a reason to adopt the full MLIR dependency or its passes for a small compiler. The 2020 preprint title is cited exactly; it should not be silently mixed with the differently titled CGO 2021 publication. Structured IR alone does not make irregular constraints affine or remove their cost.

3. **A. Pnueli, M. Siegel, and E. Singerman. “Translation validation.” TACAS 1998, pp. 151–166. DOI: 10.1007/BFb0054170.**
   - Publisher metadata/abstract: https://link.springer.com/chapter/10.1007/BFb0054170
   - Full primary PDF: https://link.springer.com/content/pdf/10.1007/BFb0054170.pdf
   - Verified full PDF pp. 151–153. Each individual compiler run is followed by validation that the target correctly implements the submitted source. A common semantics and refinement relation are explicit requirements. The analyzer can generate a proof script checked by a simpler checker. The case study translates SIGNAL to C.
   - Beryl implication (our application): distinguish a source constraint/property check from a schedule-to-source correctness check. Reuse the former only when a checked refinement establishes that the particular lowering preserves the required property. A map from lowered nodes/iterations back to source expressions and domains can provide a certificate for a small validator.
   - Limit: the paper does not promise that translation validation is cheaper than exhaustive enumeration. Our suggested local certificate design must be justified and measured. Checking that produced outputs satisfy constraints is weaker than preserving the full source result: coverage, multiplicity, order when observable, numeric semantics, and allowed inputs must also match.

4. **George C. Necula. “Proof-Carrying Code.” POPL 1997.**
   - Primary author-hosted paper (PostScript): https://people.eecs.berkeley.edu/~necula/Papers/pcc_popl97.ps
   - Author project page: https://people.eecs.berkeley.edu/~necula/pcc.html
   - Author bibliography: https://people.eecs.berkeley.edu/~necula/papers.html
   - Verified paper abstract and first two pages after local PS-to-PDF conversion. The producer supplies a safety proof relative to a stated policy; the consumer validates it with a simple, fast proof validator. This separates potentially difficult proof generation from checking.
   - Beryl implication (our application): make checking consume explicit evidence instead of repeatedly discovering the same fact. A proof DAG could share source-expression facts within one cold compilation; lowering passes attach small certificates that refer to those facts.
   - Limit: PCC verifies a safety policy, not automatically complete source/target equivalence. Cheap checking does not make generation free. The Beryl proof DAG and hash-consing design are our proposal, not a result demonstrated by PCC. `pcc_popl97_converted.pdf` is a local derivative; the downloaded original is `pcc_popl97.ps` with its own recorded hash.

5. **Nuno P. Lopes, Juneyoung Lee, Chung-Kil Hur, Zhengyang Liu, and John Regehr. “Alive2: Bounded Translation Validation for LLVM.” PLDI 2021. DOI: 10.1145/3453483.3454030.**
   - Primary author-hosted PDF: https://web.ist.utl.pt/nuno.lopes/pubs/alive2-pldi21.pdf
   - Maintained implementation: https://github.com/AliveToolkit/alive2
   - Verified abstract and introduction: automatic SMT-based validation of intra-procedural LLVM IR refinements, including LLVM undefined behavior. Resource bounds include bounded loop unrolling and time/memory limits; these can miss bugs. The paper reports 47 newly discovered LLVM bugs in its study.
   - Beryl implication (our application): specify the semantic boundary carefully, especially mathematical versus fixed-width arithmetic and failure/trap behavior. Use an independent validator for selected transformations, offline compiler development, and regression examples where it provides useful coverage.
   - Limit: do not put a general SMT solver in every cold compilation merely because Alive2 exists. It is bounded, not a proof of arbitrary unbounded loops, and its published benefits are correctness findings rather than improved compilation latency. A language with genuine finite bounds may permit complete checking, but only when those full bounds and all relevant semantics are covered.

6. **Clemens Backes. “Liftoff: a new baseline compiler for WebAssembly in V8.” V8 implementation report, 20 August 2018.**
   - Primary implementation article: https://v8.dev/blog/liftoff
   - Verified page date, byline, and implementation description. Liftoff emits machine code in one pass over function bytecode without constructing an optimizing IR; code generation runs while decoding/validating. Hot code can subsequently be recompiled by TurboFan.
   - Beryl implication (our application): use a simple first-execution path and make expensive optimizing compilation optional or deferred. Compact direct Wasm emission could avoid a C/Clang stage, while browser-native validation and machine-code compilation still remain.
   - Limit: this is a primary engineering report, not a peer-reviewed paper; browser implementations have evolved since 2018. It does not show that directly emitting a huge unrolled Wasm module is cheap. Reducing emitted representation size remains necessary, and Beryl cannot assume control over browser tiering policy.

7. **Haoran Xu and Fredrik Kjolstad. “Copy-and-patch compilation: a fast compilation algorithm for high-level languages and bytecode.” Proceedings of the ACM on Programming Languages 5 (OOPSLA), 2021. DOI: 10.1145/3485513.**
   - Primary preprint metadata: https://arxiv.org/abs/2011.13127
   - Full primary PDF, v3 dated 15 September 2021: https://arxiv.org/pdf/2011.13127
   - Publisher DOI: https://doi.org/10.1145/3485513
   - Verified abstract, stencil design, and evaluations. Prebuild binary implementation variants (“stencils”), then select, copy, and patch them at runtime. The paper reports a Wasm compiler 4.9–6.5 times faster than the contemporaneous Liftoff on its tested benchmarks. Its query compiler evaluates startup/execution tradeoffs against LLVM levels.
   - Beryl implication (our application): a later native baseline backend could move instruction selection, register variants, and assembly to toolchain-build time. A shipped stencil library is compiler infrastructure, so it can help a cold user program; it is different from memoizing the exact previous user program.
   - Limit: the paper reports platform/workload-specific results, not Beryl predictions. Its Wasm compiler turns Wasm into native machine code; it is not a browser-side scheme for bypassing browser code-generation rules. It adds target-specific artifact generation and maintenance, variant/library size, ABI, relocation, and executable-memory engineering. The paper’s libraries range from 1,666 stencils/35 kB for Wasm to 98,831 stencils/17.5 MB for the high-level language, illustrating that tradeoff. Reduce expansion and duplicate checking before committing to this backend.

## Proposed synthesis, explicitly our architecture

1. Parse and normalize once into a shared expression DAG and structured finite-domain IR. Check source constraints/properties once and retain explicit facts. Hash-consing must key the operator, operand identities, types, assumptions, relevant environment, arithmetic semantics, and checker version; a source hash alone does not justify reusing a proof under changed assumptions.
2. Choose a bounded-cost default schedule from structural facts. Keep loops and domains symbolic where possible. Do not enumerate every output merely to manufacture an enormous straight-line program. For irregular domains that cannot be compactly represented, use a measured enumerative fallback.
3. Validate the chosen lowering with a small, explicit correspondence certificate. Share source facts within this same cold compile, but validate every fact that depends on a schedule or backend. Do not remove the current repeated checks until the replacement proves the same contract.
4. Emit compact C/Wasm using loops and reusable helpers, and measure frontend/checker, planning, serialization, backend code generation, linking/instantiation, emitted size, and execution separately. Direct Wasm or a native baseline/stencil emitter is a subsequent experiment if the general-purpose backend still dominates after size reduction.
5. Put search, aggressive unrolling, and expensive optimization in a separate optional tier. Upgrade when expected execution savings exceed extra compilation cost: with extra compilation cost `C` and per-run saving `d`, the break-even count is `C/d` for `d > 0`.

These sources support the design principles; none demonstrates Beryl compile latency or validates this proposed checker. Persistent incremental query systems such as Salsa/Adapton are secondary for the stated cold-compilation target. Within-invocation fact sharing can help cold compilation; reuse of a previous program cannot establish cold performance. Equality saturation and general SMT may be useful for specific proven bottlenecks, but neither is justified as the default latency solution by these sources.
