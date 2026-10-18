# Independent A1 bounded source-adapter review

Date: 2026-10-18. Checkout: `/workspace/BerylLattice`, baseline `ebce26d9a2127540181530d0f24ada0c223e80b4`. Reviewed `source-review.diff`, the October 16 bounded source-admission design, the October 18 recovery plan, the recovered implementation and tests, the O3 inventory addition, and the implementation evidence. This review changed no repository files and did not rerun broad suites.

## Verdicts

- **SPEC PASS for the A1 bounded-name boundary and the scoped O3 dependency-closure addition.** Accepted-language preservation, original-source identity retention, deterministic bounded lookup, diagnostic remapping, fixed quotas, and required helper inventory are implemented as specified.
- **QUALITY APPROVED. No actionable findings.** The small private adapter delegates semantics to the unchanged frontend rather than introducing a second validator. Tests address the actual boundary and preservation claims, including meaningful missing-adapter and omitted-dependency failures.

These are code-review verdicts for the exact hashes below, supported by the completed focused normal/optimized product and research evidence. They do not approve F1/P1/P2, production O3 qualification, native eligibility, or scalable execution.

## Preservation and admission reasoning

`source_profiles.py:71-115` still reparses exact source bytes after validating exact public configuration records. The new cardinality, literal-shape, and rank checks are necessary conditions of the already-supported canonical stencil. They therefore cannot remove an accepted program. Fixed source/parser/profile quotas and all identity payload construction remain unchanged. The transient view never crosses the public admission boundary; the returned kernel retains `module`, not `view.module`.

`source_names_v2.py:49-72` assigns one fixed alias per distinct original spelling in first-occurrence order. A lookup compares a candidate to each resident at most once, checks lengths before character work, stops at the first unequal character, and stores at most nine original strings. No original spelling is a dictionary/set key, sorted, hashed, or compared through whole-string equality in this registry. If N is the number of visited semantic name occurrences and B the sum of their ASCII byte lengths, the actual counters satisfy candidate comparisons <= 9N and character comparisons <= 9B, including a rejected tenth spelling. These are adapter-operation bounds, not a complete compiler-work charge.

The maximum of nine follows from five required global declarations plus four axis roles. Every name used by an accepted canonical stencil must resolve to one of those roles. Global injectivity preserves both equal and unequal spellings even when namespaces overlap; in particular it preserves shape/axis shadowing, reused axes, tensor/index separation, duplicate declarations and axes, and declaration-order dependence. The unchanged validator sees one-character keys and retains responsibility for semantic rejection.

`source_names_v2.py:92-146` walks declaration roots once and derives categorized tuples from those same rebuilt declarations. It changes only semantic name fields. Source bytes/digest, original spans, declaration and child order, groups, literals, operators, types, properties, objectives and equation-kind tags are retained. Literals and constraints can be reused unchanged. Parser depth remains 32, so the recursive copying adds no newly unbounded recursion path. The returned original AST continues to be the source-oracle authority.

`source_names_v2.py:149-163` translates only the complete known name-bearing diagnostic forms. Each translation returns immediately, so original names that resemble private aliases cannot cascade. Error codes and original spans are preserved. Both shared-validation and normalization failures are remapped, with private exception context suppressed. The only observed precedence changes concern rejected sources; their exact old/new diagnostics are retained in the differential evidence.

## O3 dependency-closure reasoning

`oracle_receipt.py:37` adds `axiom.source_names_v2` to the explicit repository-module inventory. Existing `_runtime_paths` requires the actual module source origin and includes an existing `__cached__` path; qualification compares the complete required path/role set and live hashes. The adapter adds no otherwise-uncovered execution dependency: its only imports are the already-used dataclass facility and model records.

The new controls exercise (1) source and existing-cache enumeration, (2) omission of the helper source from an otherwise consistently rehashed synthetic approval graph, and (3) changed live helper source/cache bytes during selection and revalidation. Mutation uses owned temporary copies, restores each copy before the next control, and never executes synthetic cache bytes. These controls test closure mechanics; the report/protocol accurately deny production qualification and invalidate historical assumptions about the older implementation bytes.

## Evidence checked independently

- Read all implementation and added test changes; inspected the relevant unchanged frontend validator, normalizer, parser limits, public kernel construction, and O3 runtime/qualification closure.
- Verified each of the four recovered A1 files against its exact regular archive member, byte length, and SHA-256 in `recovery/unfinished-work-manifest.json`; every current file is byte-identical to its archived member. Recovery provenance is not used as an approval claim.
- Compared current `frontend.py` and `model.py` bytes directly with `git show` at the baseline: both are byte-identical.
- Verified every current file listed in `docs/reviews/2026-10-18-bounded-source/dependency-hashes.json` against its recorded hash.
- Independently compared retained baseline/integrated differential JSON: all **32 accepted records match exactly**, including identity fields, exact-source confirmation and original AST representation hashes; all **27 rejected cases remain rejected**. Both baseline and integrated normal/optimized records match. The **seven** changed diagnostic records exactly equal the documented ledger.
- Read failing-first logs: two adapter controls fail on the baseline, and the three O3 dependency methods fail before the inventory addition (four failures including source/cache subtests). Read the corresponding green logs: **10 adapter tests pass**, and **3 dependency tests pass**.
- Read final `verification.json` and completed logs: **58 product tests and 112 research tests pass in each mode** (170 normal, 170 optimized), with zero failures/errors/skips and recorded exit code 0. Exact commands, working directories and environment names are recorded in that manifest. Independently matched all recorded evidence/source hashes and checked log counts and final OK results. Research groups include state, source oracle, O3 qualification/receipt and synthetic receipt controls. These are implementer-run tests, not reviewer reruns. The initial combined import-error runs are not counted as passing suite evidence.
- `git diff --check` passes. No additional broad suites or source-admission executions were run by this reviewer; artifact/hash/differential checks above are independent review verification.

## Reviewed implementation identities

- `axiom/src/axiom/source_names_v2.py`: `e78a06b8acd0f854a04a538eda753bc7665aa3fef9bb7290358bdc447b6585c9`
- `axiom/src/axiom/source_profiles.py`: `4219fb082c4711f676897a8b0de777b504b99973560250d8a079403ff1b06328`
- `axiom/tests/test_source_names_v2.py`: `00ee2b0439e5b5198068e3d2d40f258f2d0b290097b9f1dd63163dd55e7397c6`
- `axiom/tests/test_source_profiles.py`: `54606dae5e4b388cfa809c1195f62ba225eb6e3827586d24d6ab01732279333b`
- `axiom/research/oracle_receipt.py`: `67c38bddd245621fc780e0cc56cd584f4cf92217196ffd07fcaca3a02991ea42`
- `axiom/research/tests/test_oracle_receipts.py`: `403493bc95a38bde84012f7cb464c293dbc3cc61b0ecb0a6145ef813f84137e6`
- `axiom/research/protocol/source-oracle-v1.md`: `9b6a7e37095b2676c25910025aba91bca452fb03e32b9717e920fc7fde75a294`

Controller follow-through: preserve the reviewed hashes and final verification evidence at integration and record acceptance. Complete source/graph/rule-payload accounting and fresh production oracle qualification remain separate gates.
