# Independent measurement-tool review

Reviewed Task 1 at `de89b44` and the Task 7 kernel subtask at `034d769`, against their briefs and implementation reports. Scope: all 13 files in `measurement-review-package-full.txt`. The three browser files omitted from the initial package were also read directly from immutable `de89b44` blobs before the complete package arrived. No implementation files changed and no agents spawned.

## Task 1

**Specification verdict: PASS for this instrumentation task.** The phase schema declares inclusive timing and treats absent phases as unobserved; counts remain separate from deterministic quotas/receipts. Request-local tracing introduces neither production global wrapping nor a shared collector. Fixtures cover the required shapes, parity, objectives and reservation boundaries, plus source/cap/objective/input edits. The existing process-execution benchmark retains its scope and compilation fields.

The browser cold path launches a new persistent Chromium context with a unique temporary profile and Worker for every fixture/sample/revision, closes it afterward, and completes runtime/import boot before any user-program preparation or execution. Source-fresh mode explicitly discloses potential module-code reuse. Paired revisions receive identical nonce-bearing source bytes and alternate order; raw samples retain boot, preparation, compile, instantiate, first execution and verification separately. First execution honestly includes buffer initialization and observation capture. Original-AST and independent formula audits follow timing and check both complete observations, including changed inputs.

Source/module hashes are checked against actual bytes; native generated source/executable/compiler hashes and flags are retained; browser archive identity is checked before unpacking and served runtime/harness files are recorded and audited. Python process startup and browser launch/boot have explicit distinct boundaries. Optional cProfile and trace runs are separate diagnostic preparations. The native profiler intentionally measures legacy public selection and fresh public byte emission; it does not claim to measure the later source-native API.

**Quality verdict: PASS. No important findings.** Tests cover inclusive phases, exception closure, detached snapshots, exact count validation, fixture/source consistency, local declarations and additive native compilation identities. The report supplies 18 passing Python tests, Node contract/syntax checks and independently audited native/browser smoke evidence. These checks were inspected, not rerun.

Qualification remains separate: reported self-pairs establish harness mechanics, not speedup; new integrated source-native preparation needs its own paired qualification. Research Worker boot is explicitly distinct from full product UI boot. Browser first-execution timing is an inclusive execution boundary, not callable-kernel throughput. No release-performance gate is asserted by this review.

## Task 7 callable-kernel subtask

**Specification verdict: PASS.** Source and driver bytes are snapshotted before compilation. Generated programs and the common driver compile in separate translation units, with generated `main` renamed and LTO disabled at both compilation and link. The driver performs a real external kernel call with one changing bounded input cell per iteration; retained status and rotating output captures keep calls observable. Monotonic-clock measurements exclude subprocess startup, builds, checksum calculation, oracle evaluation and replay. Mutation, capture and index bookkeeping overhead is explicitly included. One separately measured/audited warmup call precedes a buffer reset.

The direct C formula checks every timed status and rotating output, all outputs and unchanged inputs on identical untimed replay, and complete final timed state. This is accurately described as rotating timed capture plus full replay/final-state coverage; it does not claim every intermediate timed output was captured. The contract relies on deterministic, stateless generated kernels, as disclosed in the implementation report. Checksum arithmetic is unsigned and bounded stencil arithmetic remains within signed i32.

Paired samples share seeds, alternate order, retain raw elapsed/ns-per-run observations, compare checksums/final outputs and publish median, p95 and ratios. Compiler/version, exact source/driver/object/executable identities, flags and separate build durations are retained. Exclusive output creation protects existing evidence.

**Quality verdict: PASS. No important findings.** The seven reported actual-Clang tests cover correct execution and exact source identity, output/status/input faults, transient unsampled corruption caught by replay, argument validation and output preservation. Tests and driver code were inspected; the passing suite was not rerun. The disclosed 8-byte-per-iteration capture storage and fixed loop overhead should guide iteration counts; tiny smoke samples do not establish throughput acceptance. Final high-iteration serial qualification and the no-more-than-10-percent regression gate remain the coordinator's responsibility.

## Review validation

Read-only static inspection of immutable diffs/blobs and reported command evidence. No full suite, browser run, native timing run or duplicate targeted suite was performed, per the review brief. No unresolved implementation issue required an additional experiment.

## Task 1 follow-on: actual source-native profiling

Reviewed `measurement-native-review-package.txt`, the native integration brief and appended implementation report for `21f36d4` (three scoped files). Also read the immutable source coordinator interface to verify what the selected callable does.

**Specification verdict: PASS. Quality verdict: PASS. No important findings.** The profiler resolves the selected checkout's actual `compile_native_source` before timing and invokes it freshly on source bytes. Only absence of the coordinator module or API enables the original public pipeline; missing nested dependencies and runtime coordinator failures propagate. The returned artifact's actual C bytes are written and passed to the real compiler/link invocation.

The complete native preparation field measures one continuous interval from fresh source admission through linked executable completion, including file materialization. Source compilation and compiler/link intervals remain separately visible; no legacy selection/emission subdivision is fabricated. Source/plan/C identities and dimensions are checked after the timed interval; real executable output is compared with the independent formula. Compiler flags, executable identity, codegen/hint/policy metadata, deterministic work and raw sample intervals remain retained. Optional native cProfile/trace runs occur afterward and must reproduce the measured C digest; compiler diagnostics also remain separate. Paired order and existing Wasm preparation samples are preserved.

Archived trees retain exact module hashes with null observed Git revision/dirty state and a separately labeled caller-declared origin. The top-level Git-root equality check prevents an archive nested inside another checkout from inheriting its parent's HEAD. Declared provenance is explicitly not verified Git identity.

Inspected the reported 13 passing focused tests and actual paired Clang smoke evidence without rerunning them. The added tests cover real compact 15x15 generation and identity, actual legacy generation, nested import failure, full continuous timing including the file-write gap, independent small-shape native audit, separate diagnostic identity, archive provenance and CLI/output preservation. No unresolved issue warranted another experiment. The one-sample pair establishes operation, not performance acceptance; serial qualification remains outstanding.
