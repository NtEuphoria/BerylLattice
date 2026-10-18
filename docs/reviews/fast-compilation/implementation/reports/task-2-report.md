# Task 2 report

Status: DONE_WITH_CONCERNS (implementation/targeted correctness complete; timing acceptance intentionally deferred to controller's final serial qualification).

## Implementation and interfaces

- `compilation._CompilationContext(source: bytes, limits=Limits(), *, trace=None)` reconstructs exact Limits, freshly parses/admits source once, retains readonly source/kernel/limits properties, and owns candidate/check/artifact registries. `close()` revokes all retained candidate/check/emission authority.
- `context.candidate(plan)` structurally validates the actual immutable stream once and obtains exact multiplication/workspace metrics in the same validation scan. Candidate fields: `owner`, `plan`, `multiplication_ops`, `workspace_bytes`; lazy `plan_bytes` and `plan_digest` properties serialize once without revalidation. Later ranked policy can therefore filter/rank without encoding skipped candidates.
- `context.check(candidate, allowance=None, *, additional_cap=None)` returns an owned `CheckResult`, preserving all public checker semantic operations, grouping, dead work, diagnostics and accounting-v1 cutpoints. Allowance must be exact positive and at most the context's bound. Additional cap validation/constraint receipts are unchanged.
- `context.authorize(candidate, checked)` returns `_OwnedCheck` only for the exact successful receipt object issued for that candidate in this context. Fields: `owner`, `candidate`, `source`, `kernel`, `plan`, `plan_bytes`, `checked`, `limits` (actual check allowance). `_require_owned` requires an issued artifact object and live context; cloned/substituted records do not authorize emission.
- `_select_legacy(context,total_check_steps,optional_check_steps=None)` returns `(SearchResult, owned_or_none)`. It shares `selection._select_portfolio` with public `select_plan`; callbacks customize generation, checking and cached encoding without a duplicate search algorithm. Public receipt/fallback/budget behavior is retained, including committed incumbent on optional error/cancellation. Structural rejection transfers its original DecodeError to the checker receipt path without another validation scan.
- Private `_emit_native_c_checked(owned)`, `_compile_wasm_checked(owned)`, `_execute_checked(owned,data,initial_output)` share the unchanged finite lowering/interpreter bodies. Public byte APIs keep their signatures and fresh checks; external artifact digest still hashes original bytes including whitespace. Internal digest uses canonical candidate bytes.
- `prepare_compiled_demo(source, *, trace=None)` uses the owned legacy path, revokes previous preparation before new-source admission, and closes uncommitted context on failure/propagated cancellation. Request schema and default reports are unchanged. Optional trace phases use Task1 names: source_admission, candidate_generation, structural_validation, canonical_encoding, semantic_checking, code_emission, total_fresh_source_preparation; selection is an extra inclusive aggregate. No production dependency on compilation_trace is required when trace is absent.

## RED / GREEN and checks

All commands below run from `/workspace/BerylLattice-o3-fixes/axiom` unless stated.

RED:

```sh
PYTHONPATH=src python -m unittest tests.test_compilation
```

Initial newly written test module failed with `ImportError: cannot import name 'compilation' from 'axiom'`. Earlier shell invocation used the wrong relative path and did not write the file; it is not counted as the requirements RED. Seven initial ownership tests then passed after implementation. Expanded to 16 owned-compilation tests covering lazy encoding, actual metrics, cross-context/substituted records/limits, raw identity, receipts/cutpoints/caps, public fresh checks, runtime preflight, failure/cancellation lifetime, structural error handoff and trace counts.

GREEN:

```sh
PYTHONPATH=src AXIOM_TEST_NATIVE_CLANG=/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang python -m unittest tests.test_compilation tests.test_checker tests.test_codec tests.test_runtime tests.test_native_codegen tests.test_wasm tests.test_playground_service
```

115 tests PASS in 13.267 seconds, zero skips. Native tests actually compiled/executed with the configured Clang. Prior 106-test run had four obsolete service mock-target errors; mocks were moved to owned emitter/selector entrypoints while observable assertions stayed unchanged. An overbroad test edit then temporarily changed the interpreted-service selector mock; that edit was corrected and the final suite is green.

```sh
PYTHONPATH=src python - <<'PY'
import unittest
from tests.test_selection import SelectionTests
names = [name for name in unittest.defaultTestLoader.getTestCaseNames(SelectionTests)
         if name != 'test_every_admitted_shape_and_cap_boundary_against_analytic_portfolio']
result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(SelectionTests(name) for name in names))
raise SystemExit(not result.wasSuccessful())
PY
```

16 tests PASS in 0.531 seconds. Exhaustive selection corpus and full production suite deliberately left to controller integration.

Independent old/new identity comparison (run from repo root):

```sh
mkdir -p /tmp/axiom-task2-baseline
git archive a6c5531 axiom/src axiom/tests/helpers.py | tar -x -C /tmp/axiom-task2-baseline
PYTHONPATH=/tmp/axiom-task2-baseline/axiom/src python /tmp/task2-byte-identity.py /tmp/axiom-task2-baseline /tmp/task2-baseline-identity.json
PYTHONPATH=/workspace/BerylLattice-o3-fixes/axiom/src python /tmp/task2-byte-identity.py /workspace/BerylLattice-o3-fixes /tmp/task2-owned-identity.json
cmp /tmp/task2-baseline-identity.json /tmp/task2-owned-identity.json
```

PASS, exact files equal. Script/results retained in `/tmp`: each case records SHA-256 of C bytes, complete SearchResult fields/encoded bytes, full compiled-service report including exact base64 Wasm. Cases `(H,W,cap)`: `(1,1,64)`, `(5,7,64)`, `(15,15,64)`, `(15,15,128)`, `(1,127,1024)`, `(127,1,16)`. Both result files SHA-256 recorded below after execution. This is a correctness identity check, not performance evidence.

`git diff --check`: PASS.

## Self-review and limitations

- Public APIs grant no authority to receipts, candidates, or admitted metadata. Private registries prevent accidental cross-context/cloned artifact handoff; hostile Python code mutating private fields is explicitly outside this protocol's security boundary.
- Fresh public backend behavior remains intentionally redundant; only internally generated owned candidates avoid reparsing/structural revalidation/JSON decode/backend semantic recheck.
- One retained context keeps its candidate/check objects until closed or garbage collected. Service explicitly closes prior/failed preparations; no global cross-source proof cache exists.
- Legacy selector behavior intentionally remains unchanged on optional cancellation/errors. New ranked policy's stricter no-artifact failure policy belongs to Task3/Task7 integration.
- No small-case timing claim: controller instructed no performance sweeps until final serial qualification. The <=10% regression acceptance remains outstanding there.
- No exhaustive selection or full-suite claim; final integration owns those gates.

Commit: `ad9f136` — Retain owned bounded compilation checks through finite emission. Only the ten owned production/test files were staged.

Both baseline/current identity JSON SHA-256: `cb227f052c91d94df67622785df83139624d8ed0f4ad6e5f1c04702046afbd3f`.
