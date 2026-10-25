# Medici Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send a strong, honest 1517 Medici application by 2026-11-15. It needs:
- matched-thread benchmarks;
- a live demo of the theme "AI writes the fast code, beryl proves it";
- a corrected website;
- a revised Loom script and an email draft.

**Architecture:**
- **Baselines.** Two new parallel baselines join the existing single-threaded C and Rust
  ones:
  - `c-mt`: C with OpenMP, built with gcc under WSL, because the Windows clang has no
    OpenMP;
  - `rust-mt`: Rust with Rayon, built with cargo on Windows.
  The bench runner gains a `--threads N` flag. It applies one thread count to every
  parallel implementation and records it.
- **Demo B** is a small library module, `scale_candidates`. It decodes untrusted
  candidate plans from JSON, checks each one with the existing template checker, and,
  for accepted plans, verifies against the reference and times them.
- **Public-facing commands** go through a `beryl` wrapper, so no codename appears on
  screen.

**Tech Stack:**
- Python 3.13 (compiler and tests);
- clang 22 on Windows and gcc with `-fopenmp` in WSL Ubuntu;
- rustc/cargo 1.96 with `rayon`;
- the existing bench harness (`bench/run.py`, `bench/summarize.py`).

**Spec:** `docs/superpowers/specs/2026-10-25-beryl-roadmap-design.md` (Stage 0a, section 9
claims policy).

## Global Constraints

- The public name is **beryl**. The internal codename must not appear in the website, the
  video, the email, demo output or pitch documents.
- Every public speed number follows the spec's claims policy. Before Task 5's report,
  numbers say "against single-threaded C, on a 4-core Ryzen 3 3100". After it, matched
  numbers say exactly which thread counts were compared.
- Losses are reported next to wins; no result is dropped.
- Never bypass Windows Application Control (WinError 4551). Build executables under
  `.local/` or run in WSL.
- Agents never send email, post, or push. The founder sends the application.
- Commit only when the founder asks. Leave out `.swarm/`, `.claude-flow/`,
  `.blender-toolkit/` and `sessions/`.
- The shell hook blocks `$VAR`, `$(...)` and inline `python -c`. Put scripts in files.
- Keep files under 500 lines.
- Run tests with `PYTHONPATH=src python -m unittest ...` from `axiom/`.

## Review Focus

1. **The codename leaks into on-screen output** (CLI JSON, error messages, file paths
   in tracebacks).
   - Expected: every demo and wrapper command prints only "beryl" names.
   - Pinned by `test_demo_output_has_no_codename` (Task 2) and the website check
     (Task 6).
2. **A hostile candidate file:** over 1 MB, nested 10,000 deep, wrong types, NaN or
   floats.
   - Expected: it is rejected as `INVALID_PLAN` with no exception and no hang.
   - Pinned by `test_hostile_candidates_are_rejected_not_raised` (Task 1).
3. **Mixed thread counts in one comparison.**
   - Expected: every parallel implementation in a run uses the same N, each result line
     records it, and the summary marks a row whose thread counts differ instead of
     computing a ratio.
   - Pinned by `test_mixed_thread_counts_are_not_compared` (Task 4).
4. **A candidate the checker accepts whose output differs from the reference.**
   - Expected: the demo stops with a loud `SOUNDNESS ALARM` before any timing is shown.
   - Pinned by `test_accepted_mismatch_raises_alarm` (Task 1).
5. **A benchmark case beryl loses.**
   - Expected: it appears in the summary, with its ratio above 1.
   - Pinned by `test_losses_are_listed` (Task 4).

---

### Task 0: Confirm eligibility and recipient (founder, 2026-10-26)

- [ ] **Step 1:** Confirm you fit Medici's eligibility (a high-school student, college
  student or dropout in North America) on https://www.1517fund.com/medici. If not, stop
  and tell the agent, and the plan retargets.
- [ ] **Step 2:** Pick the recipient: one named 1517 team member, from 1517's own site or
  their social accounts, at `firstname@1517fund.com`. Write the name in
  `docs/pitch/medici-email.md` when Task 7 creates it.

### Task 1: Candidate plans: decode, check, verify (target 2026-10-29)

**Files:**
- Create: `axiom/src/axiom/scale_candidates.py`
- Test: `axiom/tests/test_scale_candidates.py`
- Modify: `tools/build-playground-site.py`, only if the module must ship in the release
  site, which it should not. Confirm `test_playground_site` still expects 35 modules.

**Interfaces:**
- Consumes:
  - `scale_plan.LoopPlan`, `Stage`, `plan_json`;
  - `scale_checker.check_loop_plan(source, plan, limits)`;
  - `scale_runtime.execute_loop_plan`;
  - `reference.evaluate_source`;
  - `frontend.admit_source` and `parse_source`.
- Produces:
  - `load_plan(data: bytes, max_bytes: int = 1 << 20, max_depth: int = 512) -> LoopPlan | None`.
    It converts JSON lists back to tuples and returns `None` on any malformed input.
  - `@dataclass(frozen=True) CandidateResult` with fields `name: str`, `accepted: bool`,
    `reason: str`, `detail: str | None` and `plan: LoopPlan | None`.
  - `review_candidates(source: bytes, candidates: list[tuple[str, bytes]], samples: int = 3) -> list[CandidateResult]`.
    It checks each candidate. For every accepted one it runs `execute_loop_plan` against
    `evaluate_source` on `samples` seeded inputs, including all-1023. On any mismatch it
    raises `SoundnessAlarm(name, seed)`.
  - `class SoundnessAlarm(Exception)`.

- [ ] **Step 1: Write the failing tests** in `test_scale_candidates.py`:
  - `test_round_trip`: `load_plan(plan_json(make_scale_plan(k)))` equals the original
    plan, for direct-v1 and carry-v1 on `BOX.format(h=30, w=25)`.
  - `test_hostile_candidates_are_rejected_not_raised`. Each of these returns a result with
    `accepted is False` and `reason == 'INVALID_PLAN'`:
    - `b'x' * (2 << 20)`;
    - `b'[' * 10000`;
    - `b'{"stages": 5}'`;
    - `b'NaN'`;
    - a plan whose constants are floats.
  - `test_mutants_are_reported_with_reasons`: 50 `_mutate` variants of a SUM plan give
    results whose `reason` is in `{'VALID', 'STRUCTURAL_MISMATCH', 'COVERAGE_MISMATCH',
    'ARITHMETIC_OVERFLOW', 'LOAD_OUT_OF_BOUNDS', 'INVALID_PLAN'}`, and at least 30 are
    rejected.
  - `test_accepted_mismatch_raises_alarm`: patch `check_loop_plan` to accept a forged
    plan (operands swapped in a non-commutative position, such as a load shifted by one);
    `review_candidates` raises `SoundnessAlarm`.
- [ ] **Step 2: Run them and confirm they fail.**
  Command: `PYTHONPATH=src python -m unittest tests.test_scale_candidates -v`.
  Expected: ImportError.
- [ ] **Step 3: Implement `scale_candidates.py`.** Use `json.loads` with
  `parse_constant` raising on NaN/Infinity and `parse_float` raising on floats. Check the
  size before parsing and the depth while converting lists to tuples.
- [ ] **Step 4: Run Task 1's tests plus `tests.test_scale_oracle`.** Expected: all pass.
- [ ] **Step 5: Commit**, only when the founder asks.

### Task 2: Demo B script and the `beryl` command wrapper (target 2026-11-02)

**Files:**
- Create: `tools/beryl.py`. A thin wrapper that runs the compiler CLI (`native`,
  `check`) and rewrites nothing except the program name in usage text. If CLI JSON
  output contains codename strings (for example in semantics version fields), say so in
  the task report instead of hiding it; renaming identity strings is out of scope.
- Create: `tools/demo-checked-candidates.py`. Arguments: `--source FILE`,
  `--candidates DIR`, `--out .local/demo-b/`.
  - It prints a table: name, verdict, reason, time (accepted only), speed against the
    direct-v1 plan.
  - It ends with one summary line: `N candidates: R rejected (by reason), A accepted;
    fastest X.XXx; every accepted plan matched the reference`.
- Create: `docs/pitch/agent-plan-prompt.md`. A prompt that gives Claude or Codex the
  source program, the `beryl-loop-plan-v1` format, two example plans, and the request
  "write 10 faster candidate plans as JSON files".
- Create: `bench/demo_b/` with `program.ax` (`box3x3` at 254x254, no cap) and
  `candidates/`:
  - planner plans: `direct.json`, `carry.json`;
  - 10 mutants from `_mutate`, seed 20261102;
  - the agent-written files the founder collects using the prompt.
- Test: `axiom/tests/test_scale_candidates.py`. Add `test_demo_output_has_no_codename`,
  which runs the demo script on a 2-candidate temporary directory and asserts
  `'axiom' not in stdout.lower()`.

- [ ] **Step 1:** Write `test_demo_output_has_no_codename`. Run it; expect a FAIL (no
  script yet).
- [ ] **Step 2:** Implement `tools/demo-checked-candidates.py`. Time accepted plans with
  `emit_scale_c`, clang `-O3` and `bench/impl/axiom_native_harness.c`, executables under
  `.local/demo-b/`, as in `.local/carry_bench.py`. Verification comes from Task 1's
  `review_candidates`, before any timing.
- [ ] **Step 3:** Implement `tools/beryl.py`. Run
  `python tools/beryl.py native bench/demo_b/program.ax --out .local/demo-b/k.c` and
  read the output for codename strings. Expected: none, or a note in the report.
- [ ] **Step 4:** Founder: paste `docs/pitch/agent-plan-prompt.md` into Claude and Codex,
  and save their JSON files under `bench/demo_b/candidates/agent-*.json`.
- [ ] **Step 5:** Run
  `python tools/demo-checked-candidates.py --source bench/demo_b/program.ax --candidates bench/demo_b/candidates`.
  Expected: some agent candidates rejected with reasons, the accepted ones matching the
  reference, and the summary line printed. Save the output to
  `.local/demo-b/run-1.txt` for the video.
- [ ] **Step 6:** Run the full test module. Expected: pass.

### Task 3: Rust with Rayon baseline (`rust-mt`) (target 2026-11-04)

**Files:**
- Create: `bench/impl/rust_mt/Cargo.toml` (package `kernels_mt`,
  `rayon = "1.10"`, `[profile.release] opt-level = 3`).
- Create: `bench/impl/rust_mt/src/main.rs`.
  - Same argv, protocol, JSON fields and checksum as `bench/impl/kernels.rs`, with
    `"impl":"rust-mt"` and an added field `"threads":N`.
  - It covers the 10 kernels beryl compiles: sq2x2, stencil1d3, box3x3, laplace5,
    conv3x3, polymap, transpose, sum, dot, matmul.
  - Thread pool size comes from env `BENCH_THREADS`, via
    `rayon::ThreadPoolBuilder::new().num_threads(n).build_global()`.
  - Parallelize over output rows (`par_chunks_mut`). sum and dot use `par_iter().sum()`.
- Modify: `bench/run.py`. In `build()`, add `rust-mt`:
  `cargo build --release --manifest-path bench/impl/rust_mt/Cargo.toml`; the executable
  is `bench/impl/rust_mt/target/release/kernels_mt(.exe)`. Add `'rust-mt'` to `IMPLS`.

- [ ] **Step 1:** Write `bench/impl/rust_mt/src/main.rs`, reusing the single-threaded
  kernel bodies with parallel outer loops.
- [ ] **Step 2:** Run `cargo build --release --manifest-path bench/impl/rust_mt/Cargo.toml`.
  Expected: it builds. If crates.io is unreachable, record it and skip `rust-mt`, noting
  that in Task 5's report.
- [ ] **Step 3:** Run
  `python bench/run.py --kernels sq2x2,sum,matmul --sizes s,m --impls rust,rust-mt --no-axiom-sweep --results .local/mt-check`.
  Expected: every `rust-mt` result has `status ok` with oracle-verified checksums.

### Task 4: C with OpenMP baseline (`c-mt`), the `--threads` flag, and a summary that refuses mismatches (target 2026-11-06)

**Files:**
- Create: `bench/impl/kernels_mt.c`. The `kernels.c` protocol with
  `#pragma omp parallel for schedule(static)` on the output-row loop of the same 10
  kernels; `reduction(+:s)` for sum and dot. Prints `"impl":"c-mt","threads":N` using
  `omp_get_max_threads()`.
- Modify: `bench/run.py`:
  - add `c-mt` to `build()`: `[args.cc, *args.cflags.split(), '-fopenmp', '-std=c11', kernels_mt.c]`;
  - add `--threads N`, which sets `BERYL_THREADS`, `BENCH_THREADS` and
    `OMP_NUM_THREADS` to N for child processes and stores `threads` in the run header
    and every result line;
  - add `'c-mt'` to `IMPLS`.
- Modify: `bench/summarize.py`:
  - add `c-mt` and `rust-mt` to `ORDER`;
  - add a header line `Threads: N` from the run header;
  - in ratio cells, compare only results with the same `threads` value, showing
    `threads differ` otherwise;
  - add a "Losses" list: every case where axiom-native's ratio against any compared
    implementation is above 1.
- Test: create `bench/test_summarize_threads.py` (stdlib unittest) with:
  - `test_mixed_thread_counts_are_not_compared`: a synthetic log with c-mt at threads=4
    and axiom-native at threads=7. The cell contains `threads differ`.
  - `test_losses_are_listed`: a synthetic log where axiom-native is slower on one case.
    That case appears under "Losses".

- [ ] **Step 1:** Write `bench/test_summarize_threads.py`. Run
  `python -m unittest bench/test_summarize_threads.py`. Expected: FAIL.
- [ ] **Step 2:** Implement the `summarize.py` changes. Run the tests. Expected: PASS.
- [ ] **Step 3:** Write `kernels_mt.c` and the `run.py` changes.
- [ ] **Step 4:** In WSL, run
  `python3 bench/run.py --cc gcc --kernels sq2x2,sum --sizes s,m --impls c,c-mt,axiom-native --threads 4 --no-axiom-sweep --results .local/mt-check-linux`.
  Expected: every result is ok and verified, and `threads` is 4 on every line. If
  `-fopenmp` fails to link, install `libgomp1` only after asking the founder.

### Task 5: Run the matched benchmarks and write the report (target 2026-11-08)

**Files:**
- Create: `docs/reviews/2026-11-08-matched-benchmarks.md`

- [ ] **Step 1:** Single thread on Windows:
  `python bench/run.py --kernels sq2x2,stencil1d3,box3x3,laplace5,conv3x3,polymap,transpose,sum,dot,matmul --sizes s,m,l --impls c,rust,axiom-native --threads 1 --no-axiom-sweep --results .local/matched`.
- [ ] **Step 2:** N threads on Windows, the same command with `--impls rust-mt,axiom-native --threads 4`.
- [ ] **Step 3:** N threads on Linux (WSL, gcc), with
  `--cc gcc --impls c,c-mt,axiom-native --threads 4`.
- [ ] **Step 4:** Use 4 threads, the physical core count, in every N-thread run; say so in
  the report.
- [ ] **Step 5:** Summarize each log with `bench/summarize.py`. Write the report:
  1. the machine and toolchains;
  2. three tables, one per run;
  3. the losses list;
  4. one paragraph on what changed from the earlier all-cores-against-one claim;
  5. the exact claim sentences now allowed, which go into the Loom script and the
     website.
- [ ] **Step 6:** Founder reviews the report before any number goes public.

### Task 6: Fix the website (target 2026-11-10)

**Files:**
- The published artifact at https://claude.ai/artifact/DrF6syu4wLpQmUgyjKvEkC.

- [ ] **Step 1:** Read it with the Artifact tool (`action: read`). Note whether the
  founder has writer access.
- [ ] **Step 2:** Make these edits:
  1. remove every codename occurrence, including the "Project" card and the repro
     commands;
  2. replace the invalid fail-safe example with a program that `beryl check` admits,
     taken from `axiom/docs/window-stencils.md`;
  3. relabel the Rust table as process latency;
  4. replace the static "live gates" panel with dated, sourced figures;
  5. put Task 5's matched numbers, and the claim sentences from its report, in place of
     the all-cores-against-one numbers;
  6. state the 2²⁴-cell scale limit and the i64 support correctly.
- [ ] **Step 3:** Search the fixed HTML for the codename, case-insensitive. Expected: 0
  hits. Validate the example by saving it to `.local/site-example.ax` and running
  `python tools/beryl.py check .local/site-example.ax`. Expected: admitted.
- [ ] **Step 4:** Republish to the same URL if the founder has writer access; otherwise
  publish a new artifact and give the founder the link.

### Task 7: Loom script v1 and v2, and the email draft (v1 2026-11-09, v2 2026-11-12)

**Files:**
- Create: `docs/pitch/medici-loom-script.md`
- Create: `docs/pitch/medici-email.md`

- [ ] **Step 1: Script v1, timed to 5:00 at a speaking pace of about 140 words a
  minute:**
  - 0:00–1:00: who you are and how you came to this;
  - 1:00–1:45: the problem: fast code is often silently wrong, and now AI writes much
    of it;
  - 1:45–3:15: the live demo:
    1. compile a kernel;
    2. show the overflow refusal and its fix;
    3. run demo B's candidate table;
    4. show the matched benchmark chart;
  - 3:15–4:15: why you're dedicating yourself: the roadmap to AI and real-time work, in
    one breath each;
  - 4:15–5:00: what the grant buys: AI development tools as a team of agents, plus
    compute; and what you'll show 1517 in 90 days.
  Every number cites Task 5's report.
- [ ] **Step 2:** Founder records a practice take and notes what felt stiff or long.
- [ ] **Step 3: Script v2.** Apply the notes, cut to 4:45, and check every claim against
  the spec's claims policy.
- [ ] **Step 4: Email draft:**
  - subject line;
  - three sentences: who you are, what beryl is, the ask;
  - the Loom link;
  - the repository and site links;
  - one line on availability for a call.
  - Recipient from Task 0. No codename anywhere.

### Task 8: Record and send (founder, by 2026-11-15)

- [ ] **Step 1:** Record the Loom from script v2, with demo B's output and the chart on
  screen.
- [ ] **Step 2:** Re-read the email and links, checking that the website and repository
  show no codename and that the video is shared publicly by link.
- [ ] **Step 3:** The founder sends the email.
- [ ] **Step 4:** Note the send date in `docs/pitch/medici-email.md`. Follow up once,
  briefly, if there's no reply by 2026-11-29.
