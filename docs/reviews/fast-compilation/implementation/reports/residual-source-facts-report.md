# Within-proof source producer facts

Status: implemented; targeted validation passed; independent review, aggregate
full-suite verification and performance qualification remain controller-owned.
Commit: `2fdc48f241b365950998688413c2ab2cac21a246` (four owned code/test files).
This report lives in the existing ignored `.superpowers` review workspace.

## Change and equivalence argument

- Each `_Expressions` arena owns its producer facts and the exact live admitted
  kernel object. This fixes retained AST, axes/tensor names, shape and interval
  assumptions. No receipt, label, formula, persisted cache or digest authorizes a
  source term. Public `check_plan` still reparses/readmits original bytes.
- Keys include concrete row/column plus values for every actually referenced
  producer free name. An iterative original-AST walk finds those names; unrelated
  outer output bindings are excluded. Replacing the kernel owner clears facts.
- The first concrete binding runs the original AST interpreter, including every
  index, group and scalar visit. Only successful, conclusive evaluations install
  a node plus observed work/allocation deltas. Failed or inconclusive terms do
  not install facts. These deltas are bounded by already successful quota use;
  there is no recursive weight computation or large symbolic arithmetic.
- A cache hit skips interpretation only when BOTH entire deltas fit. It charges
  the same conceptual work and explicit virtual allocation count. Otherwise the
  original interpreter runs and reproduces every work/allocation interleaving,
  including the exact first exhaustion, overflow, witness and diagnostic.
  Since a fitting cached term previously completed with identical semantics and
  assumptions, it has no failure or new inconclusive side effect to replay.
- Physical immutable nodes can be shared; equality still visits/charges every
  conceptual pair. Every actual/dead plan operation still executes. Checker
  version, accounting version, limits and public result fields are unchanged.
- The narrow authorized selection-test repair replaces physical-call-derived
  quota with baseline golden 164 = 124 conceptual source + 40 physical plan
  allocations. The 163 failure / 164 and 165 success assertions remain.

## RED / GREEN evidence

All commands run from `/workspace/BerylLattice-o3-fixes/axiom`.

1. Before production changes:

   ```sh
   PYTHONPATH=src python -m unittest tests.test_source_facts.SourceFactTests.test_each_concrete_source_producer_is_evaluated_once_per_proof tests.test_source_facts.SourceFactTests.test_renamed_output_axes_do_not_prevent_reuse_or_cross_invocations -v
   ```

   RED: 2 failures, both `41 != 27` actual input-node evaluations. The first
   statement after eligibility/work checks demonstrated missing reuse rather
   than an API/import/setup failure.

2. First implementation validation:

   ```sh
   PYTHONPATH=src python -m unittest tests.test_source_facts.SourceFactTests.test_each_concrete_source_producer_is_evaluated_once_per_proof tests.test_source_facts.SourceFactTests.test_renamed_output_axes_do_not_prevent_reuse_or_cross_invocations tests.test_source_facts.SourceFactTests.test_every_small_work_and_allocation_prefix_matches tests.test_source_facts.SourceFactTests.test_joint_prefixes_include_cache_hit_and_source_plan_boundary tests.test_source_facts.SourceFactTests.test_actual_free_bindings_and_retained_ast_supply_interpreter_facts tests.test_source_facts.SourceFactTests.test_source_overflow_and_inconclusive_effects_keep_precedence tests.test_checker -v
   ```

   GREEN: 35 tests, 7.691 s, no failures/skips. Existing checker tests passed
   unchanged, including strict work/allocation and late-metric boundaries.

3. Full new focused file (before the final equivalent quota-guard cleanup and
   addition of the owned-check isolation test):

   ```sh
   PYTHONPATH=src python -m unittest tests.test_source_facts -v
   ```

   GREEN: 10 tests, 89.355 s, no failures/skips. Includes every field of every
   CheckResult for all 955 shapes × all three schedules against original checker
   39dc2f6; individual every-budget/every-allocation prefixes for 1×2, 2×1, 2×2
   and all schedules; combined cutpoints around source cache hits and source/plan
   boundary; grouped, renamed, reordered source; forged records; invalid and dead
   overflow plans; semantic unknowns; synthetic free-binding/source-overflow/
   inconclusive/unsupported-operator cases with every joint quota prefix.

4. Existing selection-test incompatibility explicitly reproduced before repair:

   ```sh
   PYTHONPATH=src python -m unittest tests.test_compilation_selection.RankedSelectionTests.test_source_expression_quota_exact_boundary -v
   ```

   RED: expected-success assertions failed at physical counts 115 and 116, which
   correctly cannot meet the accounting-v1 quota. After the authorized golden
   164 repair, GREEN: 1 test, 0.007 s, no failures/skips.

5. Final targeted integration verification (all original checker tests, all new
   tests except the already run 955-shape sweep, all non-exhaustive ranked tests):

   ```sh
   PYTHONPATH=src python - <<'PY'
   import unittest
   from tests import test_checker, test_source_facts, test_compilation_selection
   suite = unittest.TestSuite()
   loader = unittest.defaultTestLoader
   suite.addTests(loader.loadTestsFromModule(test_checker))
   for name in loader.getTestCaseNames(test_source_facts.SourceFactTests):
       if name != 'test_all_admitted_shapes_and_schedules_match_original_results':
           suite.addTest(test_source_facts.SourceFactTests(name))
   suite.addTests(loader.loadTestsFromTestCase(test_compilation_selection.RankedSelectionTests))
   result = unittest.TextTestRunner(verbosity=2).run(suite)
   raise SystemExit(not result.wasSuccessful())
   PY
   ```

   GREEN: 62 tests, 9.613 s, no failures/skips. The new owned-check test compares
   original full CheckResult/work cutpoints at expression quotas 163/164/165 and
   confirms two checks sharing the same retained kernel still start fresh arenas.
   `git diff --check` passed.

6. Post-cleanup pre-commit smoke check:

   ```sh
   PYTHONPATH=src python -m unittest tests.test_source_facts.SourceFactTests.test_each_concrete_source_producer_is_evaluated_once_per_proof tests.test_source_facts.SourceFactTests.test_owned_checks_keep_exact_boundary_and_start_a_fresh_arena tests.test_compilation_selection.RankedSelectionTests.test_source_expression_quota_exact_boundary -v
   ```

   GREEN: 3 tests, 0.050 s, no failures/skips. Snapshot SHA-256 and diff whitespace
   were rechecked before committing only the four owned code/test files.

## Counts, fixture and self-review

For the independently authored 2×2 SSA staged control, old/new conceptual counts
are unchanged: 476 work steps and 164 allocations. Physical allocations fall
164 → 115; input-node evaluations fall 41 → 27. A renamed output-axis source
gets the same reduction; each cold proof performs its own 27 input evaluations.
These are deterministic call counts, not performance claims.

`tests/fixtures/checker_39dc2f6.py` is a byte-for-byte test-only snapshot of the
immutable original checker. SHA-256 is
`bfe22abb6142f63e4d868570916ea7ad64e13b5011fd54cfafeea618ec73aaa5`, enforced
by a test. It imports current codec/frontend/model records to isolate checker
semantics; codec equivalence is owned by the sibling validator work. No baseline
workspace files were modified and no baseline is imported by production.

Self-review: sharing changes only physical node identity/storage, which no public
result exposes. Virtual allocation checks precede append exactly as old physical
checks did. Bulk charges use bounded current/observed sums, not subtraction from
possibly huge caller-supplied limits. Conclusive cached terms never clear global
inconclusiveness. Failed terms cannot reach the remember continuation. Cached
terms do not suppress original output AST work, finite plan work or equality.
The assumptions are the existing immutable freshly admitted finite source AST,
one source/interval per arena, and the existing scalar semantics; this change
does not extend the admitted source language or scalable proof capability.

Controller explicitly requested one final aggregate unittest discovery after all
parallel changes/reviews stabilize; this agent did not duplicate that run or run
performance sweeps. No known correctness blocker remains from these checks.
