# Gaps, research and improvement plan (2026-10-19)

Scope: Project Axiom (public name beryl) on `feat/bench-native` at `ccdb0c9`, measured on Windows 11 with
clang 22.1.6 and rustc 1.96.0. Evidence comes from `bench/results/` (runs `20261019T005748Z`,
`20261019T020527Z` and `20261019T021745Z`) and from full test-suite runs on this machine. This is a
working document: section 5 records what was implemented and how it was verified.

## 1. Where we stand

| Area | State | Evidence |
|---|---|---|
| Native speed (admitted kernels) | Leads C in 18 of 18 cases; 0.43x C, 0.32x Rust, 0.53x hand-written C (geometric means) | `bench/results/20261019T020527Z-73191bf-analysis.xlsx` |
| Cold native compile | ~0.3 s median (Axiom check+emit ~90 ms, then clang and link) | same run |
| Checked interpreter | ~10^5 x C; re-proves every plan per request by design | Interpreter phases sheet |
| Correctness checks | Independent checker, 128-case golden test, exact compact-loop correspondence, every benchmark output checked against `bench/oracle.py` | `axiom/tests`, bench logs |
| Coverage | 6 of 42 kernel/size combinations | Coverage sheet |

## 2. Downfalls

### 2.1 Ease of use (largest gap)

1. **Expressiveness.** Only two-stage window stencils with at most 256 input cells are admitted. No
   reductions, conditionals, `max`, transposed reads or second inputs. 36 of 42 combinations refused.
2. **No binary minus.** A Laplacian has to be written `4*p[r+1,c+1] + -1*p[r,c+1] + ...`.
3. **Unhelpful rejections.** Programs outside the admitted forms get one of two fixed sentences
   (`requires exactly two shapes, one input, one producer and one output` or
   `source is outside the exact canonical stencil profile`), with the error offset at byte 0. Neither
   says which declaration or expression is wrong or what would be accepted.
4. **Undocumented family.** Nothing explains the two-stage window rules, and the playground offers only
   the original stencil, so nobody discovers the new kernels. Fast convolutions require the author to
   know to write them separably.
5. **Stale public text.** The release builder's generated README still says the demo supports "one exact
   i32 two-stage stencil" (a publication decision for the owner; not changed here).

### 2.2 Safety and verification process

1. **Noisy test baseline.** 73-88 tests fail on unchanged code on this machine, so "no new failures" is a
   comparison against noise, and a real regression in those modules could hide. Causes, measured:
   - POSIX directory descriptors: `os.O_DIRECTORY` does not exist on Windows (evidence,
     artifact-chunk, invocation and compile-CLI modules; about 30 tests). These modules deliberately use
     directory handles for race-free publication, so this is a platform limit, not a bug to patch over.
   - Windows privilege for symlinks (`WinError 1314`).
   - Core runner/toolchain probes returning `infrastructure_error` without the pinned Core toolchain.
   - Windows Application Control blocking or locking freshly built test binaries (varies per run).
   - One real Windows bug: `tools/benchmarks/kernel-throughput.c` uses `clock_gettime`, which the
     MinGW/UCRT link here does not provide.
2. **Unreviewed proof-boundary changes.** This week changed what is admitted (window family) and how
   compact loops are trusted (family hints, the hint size bound). The handoff requires independent review
   for such changes; none has been run.
3. **Single copy.** Nothing from this week is pushed; `feat/axiom-bounded-source` (`bee32b5`) is still
   unmerged.

### 2.3 Performance

1. **Scale.** Every input above 256 cells is refused. This is the compact-loop proof gate (C1/F1), not
   tuning.
2. **Interpreter latency** in the playground (~0.25-0.4 s per request). Caching checked plans per session
   would remove most of it, but must keep the fresh-check rule explicit.
3. The canonical stencil still uses the early-exit input check because its bytes are published.

## 3. Research

**Binary minus.** Options: (a) a new `sub` plan opcode, which touches the plan format, hint format,
runtime, checker and four code generators, and changes plan identities; (b) define `a - b` as exactly
`a + (-1)*b` in the parser. (b) changes nothing downstream: the checker proves the result like any
`+`/`*` expression, and the only semantic difference is that `-1*b` is itself an i32-checked node,
which can overflow only for `b = -2^31` (impossible for admitted inputs, and caught by the checker if a
constant produced it). Chosen: (b), documented as the definition of `-`. Subtraction stays unavailable in
index expressions, with a specific message, because family indices are `axis + k` with `k >= 0`.

**Diagnostics.** The recognizer (`window_family.window_shape`) decides admission on the normalized
profile and must stay the single source of truth. A separate explainer can walk the retained AST, which
still has byte spans, and report the first rule broken with its location and a fix. The explainer never
admits anything; it only words the rejection, so it cannot weaken admission. Error codes stay unchanged
(tests and clients depend on codes, not text).

**Examples and guide.** The service owns the example list and the UI owns their titles; both need the new
entries. A user guide belongs in `axiom/docs/` next to the existing playground documentation.

**Test health.** Skipping POSIX-only tests on Windows would make the suite quiet but could hide changes,
and those tests guard security-relevant code. Chosen instead: a classifier that sorts every failure by its
measured cause and lists anything unexplained as a possible regression, plus a fix for the one real
Windows bug.

**Reductions (next).** A `sum(k in 0..N: e)` that desugars to `+` keeps the checker unchanged, but alone
it only unlocks `sum`: `dot` and `matmul` need a second input tensor, and a left fold of 256 terms exceeds
the parser's depth-32 limit unless the association is defined as a balanced tree. That is a language
design decision (association order is part of the semantics), so it is planned, not implemented here.

## 4. Plan

| # | Change | Area | Acceptance |
|---|---|---|---|
| 1 | Binary `-` in scalar expressions, defined as `a + (-1)*b`; specific error for `-` in indices | Ease of use | Laplacian written with `-` is admitted, checked and equal to the reference; canonical identities unchanged |
| 2 | Located, specific rejection messages from an AST explainer | Ease of use | Each family rule has a test asserting code, message and offset; admission results unchanged |
| 3 | Separable convolution and Laplacian playground examples; window-stencil user guide | Ease of use | Examples run in the service and compiled paths; guide examples are admitted by a test |
| 4 | Failure classifier `tools/classify-test-failures.py`; fix `clock_gettime` on Windows in the kernel benchmark | Safety | Classifier explains every baseline failure; kernel benchmark test builds on Windows |
| 5 | Verify: full suite classified, golden and family tests, benchmark spot-check, playground smoke test | All | No unexplained failures; benchmark within noise of the last run |

Later, in order: independent review of the window-family and compact-hint changes (owner's call), push
and merge `bee32b5`, reductions with a second input, conditionals and `max`, plan caching, the scalable
proof gate.

## 5. Results

| # | Delivered | Verified by |
|---|---|---|
| 1 | `a - b` parses to exactly `a + (-1)*b` in scalar expressions; `-` in an index or shape is a `SYNTAX_ERROR` at the operator, with a hint | `test_subtraction_scope_and_invalid_tokens`: same semantic digest as the `+-1*` spelling; canonical identities unchanged (golden checker test passes) |
| 2 | `window_explain.py` words rejections: it names the broken rule and points at the offending declaration or read. Admission still comes only from the recognizer; codes are unchanged | `test_rejections_name_the_rule_and_location`: five rules, message and byte offset each, plus the counts message |
| 3 | Playground examples `separable-blur` (selects `rows-v1`) and `laplacian` (written with `-`, selects `inline-v1`); guide `axiom/docs/window-stencils.md` | `test_window_guide` runs all four guide programs through admit, select, execute and the reference evaluator; service, HTTP and public-site tests cover the five examples |
| 4 | `tools/classify-test-failures.py`; `kernel-throughput.c` uses `QueryPerformanceCounter` on Windows; `measure-kernel.py` names the executable `.exe` on Windows | All 7 kernel-benchmark tests now pass (2 were in the baseline). Three of them had passed before only because the failed link printed "audit"; once the link worked they exposed the `.exe` naming bug, now fixed |
| 5 | Verification below | |

**Full suite** (493 tests, `.local/gaps-tests.txt`): 100 failing before the item-4 fixes, sorted as:
- app-control: 8
- POSIX `O_DIRECTORY`: 34
- symlink privilege: 2
- Core toolchain: 9
- `#!` fake compilers: 4
- unexplained: 10

Of those, 6 were the kernel benchmark and the playground count, both fixed and re-run green. The affected suites (frontend, guide, family, compact, golden checker, playground service, HTTP and site, kernel benchmark) give 97 tests OK. The full suite was not re-run after these fixes.

**Still unexplained** (all in the earlier baseline, so not caused by this round; not diagnosed):
- `test_compilation_trace` (2)
- `test_compile_cli` `KeyError: 'source_emission'`
- `test_core_runner` background-children check

**Classifier limits.** Two causes are matched by test name, because the traceback cannot show them:
- the CLI child reports `O_DIRECTORY` only in its JSON output;
- the toolchain tests' fake compilers are `#!` scripts.

Both were reproduced by hand. Name matching can hide a regression in those tests, so the `--baseline` comparison stays the regression gate.

**Benchmarks** (`.local/spot-results/`, size `s`, `hash` pattern, against run `20261019T020527Z`):
- `box3x3`, `conv3x3`, `laplace5`, `polymap` and `stencil1d3` are within 1% of that run.
- `sq2x2` measured 412 ns once, then 281-333 ns on three re-runs, against 281 ns before. C varies just as much here (375-613 ns), so this is noise at timer resolution.

**Hygiene.** The new and changed files are LF-only, and the public modules contain no codename.

**Open decision found during verification.** In the public build, window-family plan identities equal the private ones: `window-stencil-i32-v1` carries no codename, so the release rename does not touch it. Only canonical identities differ between builds. The site test now states this explicitly. Whether to rename family identities in public builds is the owner's call.

**Not done in this round:**
- README wording (item 2.1.5)
- independent review of the proof-boundary changes
- push
- reductions
