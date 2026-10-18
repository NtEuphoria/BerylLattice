# Independent review: within-proof source facts

**PASS — no material findings.** Reviewed immutable commit
`2fdc48f241b365950998688413c2ab2cac21a246` against the requirements in
`residual-source-facts-review-package.txt`, then reviewed implementation and test
quality. This is a scoped static review, not an independent test or performance
qualification. No tests, corpus sweeps, benchmarks, or production edits were run.

## Spec compliance

- **Actual source and assumptions:** `axiom/src/axiom/checker.py:128` walks the
  retained producer AST, including grouped expressions and read indices, to find
  referenced names. At `:156` the arena retains the exact kernel object and
  discards facts when that owner changes. At `:215` the key uses concrete
  coordinates and actual free-name values after producer-axis rebinding. Thus
  output-axis renames do not inhibit sharing, differing free bindings cannot
  share a term, and labels/digests are not semantic authority. The owning kernel
  and fresh arena fix the retained AST, dimensions, tensor names and input
  interval. The model's admitted records are frozen and contain immutable AST
  records/tuples (`model.py:57`, `:141`, `:157`).
- **Successful terms only:** the `remember` continuation at `checker.py:188`
  runs after the entire producer evaluation and installs a fact only while the
  arena remains conclusive. Overflow, unsupported operations, quota failures or
  invalid indices exit before installation. The inconclusive flag is monotone;
  a previously successful fact cannot clear it. Reusing such a fact after some
  other operation becomes inconclusive is therefore also safe.
- **Every quota prefix:** `checker.py:88` enforces virtual allocations before
  physical append. At `:220`, a hit is skipped only when both its complete work
  and allocation deltas fit. Such a deterministic, previously successful term
  has no intermediate failure to expose. If either delta does not fit, `:229`
  executes the original interpreter, preserving charge/allocation ordering and
  the first failure even when both quotas cut through the term. Exact-fit hits
  leave the next operation to fail exactly as before. Deltas come from observed
  successful execution; they do not recursively compute exponential weights or
  perform arithmetic on the magnitude of caller-supplied quotas.
- **Equality and finite execution:** `checker.py:240` still charges every
  conceptual node pair, including repeated shared children; there is no identity
  shortcut or visited-pair cache. Source overflow behavior (`:104`) and the
  complete physical operation loop (`:370`) are unchanged. Physical node indices
  do not appear in result fields or witnesses.
- **Trust and isolation:** public checking still reparses/readmits original
  bytes, compares source identity, and uses the fresh AST (`checker.py:326`).
  Both public and owned checks construct a new arena at `:355`; no producer fact
  crosses checks or candidates. Public result fields, checker version and
  accounting version are unchanged by this commit.

## Test integrity and quality

- Independently verified SHA-256
  `bfe22abb6142f63e4d868570916ea7ad64e13b5011fd54cfafeea618ec73aaa5`
  for all three: the committed fixture, `git show 39dc2f6:axiom/src/axiom/checker.py`,
  and the extracted baseline checker. This is the original checker, not a
  reconstructed oracle. The fixture deliberately imports current frontend/codec
  records; the differential isolates checker semantics and does not independently
  qualify those other components.
- `test_source_facts.py:62` compares all dataclass result fields. The tests cover
  every admitted shape and schedule, individual budget/allocation prefixes,
  joint boundary prefixes, public/owned isolation, grouped/renamed/reordered
  source, forged records, dead overflow and invalid plans. The synthetic private
  interpreter cases at `:207` and `:228` compare expression trees, counters,
  inconclusiveness and failure witnesses under all their joint prefixes; they
  exercise free bindings and unsupported/overflow cases beyond public admission.
  The string replacements for source variants match the literal fixture text.
- The selection-test adjustment at `test_compilation_selection.py:267` preserves
  the existing conceptual quota instead of deriving it from fewer physical
  calls. Independently, the hand-authored 2×2 control requires `4*31 = 124`
  source allocations and `1 + 9*3 + 4*3 = 40` plan allocations, totaling **164**.
  Its work remains `4*77 + 44 + 4*31 = 476`. Nine unique producer terms need
  `9*7 + 4*3 = 75` physical source nodes; adding the 40 plan nodes explains
  **115** physical allocations without weakening the **164** quota.
  The unchanged existing checker boundary test asserts the same 164 formula.
- The change is localized to the arena/interpreter and three test files. It
  neither introduces a production baseline copy nor changes limits, admission,
  plan validation, loop semantics or backend behavior.

The package's RED/GREEN history and 955×3/targeted test outcomes were inspected
as supplied evidence, not rerun here. Final aggregate testing and timing remain
controller-owned. This review found no correctness or test-integrity blocker to
that qualification.
