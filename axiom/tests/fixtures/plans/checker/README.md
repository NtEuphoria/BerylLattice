# Independent checker controls

These plans do not come from `axiom.planner`.

- `manual-inline-1x1.json` explicitly spells out the four input loads, four producer squares and three left-associated consumer additions. Its placeholder semantic hash is replaced with the independently admitted test source hash.
- `manual-ssa-staged-5x7.json` retains all 48 producer results in SSA registers and then emits 35 consumers: 285 operations, 48 multiplication opcodes and no scratch arena. The independent `staged` authoring routine in `test_checker.py` records the hand-chosen schedule and asserts this fixture exactly; it is outside the production candidate portfolio.
- `manual-uninitialized-scratch.json` reads an in-bounds slot before any write. Its placeholder semantic hash is replaced at test time so the semantic check reaches the intended violation.

Further adversarial plans are constructed directly from these records in the checker tests, including overwritten scratch, malformed SSA, altered grouping, unsafe dead arithmetic and bounded deep DAG controls.
