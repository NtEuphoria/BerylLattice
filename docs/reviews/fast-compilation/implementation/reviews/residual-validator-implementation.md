# Residual structural-validation hot path

## Change and boundaries

`axiom/src/axiom/codec.py` formats operation/operand/origin diagnostic paths only on failure. Its hot loop uses exact-type integer guards and inline canonical-size quota checkpoints. The two fixed header integer checks still use `_integer`. No trusted-generator path, memoization, alternate encoding, public API change, or metrics shortcut was introduced.

Check order is unchanged: exact record/opcode/destination/operand/index/literal/origins-tuple checks, operation-shell quota, minimum origins quota, then each exact origin check and its additional digit quota. Every bool remains rejected where an exact integer is required. Actual multiplication/workspace metrics return only after the entire stream passes. Canonical serialization and its bytes are unchanged.

## Immutable differential oracle

`axiom/tests/fixtures/codec-21f36d4.py.txt` is the verbatim complete codec from commit `21f36d4e977ff950276fbfff6198d8640bb24029`, path `axiom/src/axiom/codec.py`. It is a test fixture only, loaded into a separate module with its own validator helpers. The fixture is 17,371 bytes with SHA-256 `5c8c67adb70760ffe7b4907701e8655a4af7b21d17cec26c5aba4247c46ebf49`; the test verifies this identity before executing it. Git was used only when generating the fixture:

```python
source = subprocess.check_output([
    'git', 'show',
    '21f36d4e977ff950276fbfff6198d8640bb24029:axiom/src/axiom/codec.py'])
Path('axiom/tests/fixtures/codec-21f36d4.py.txt').write_bytes(source)
```

Runtime tests require neither Git nor historical commit objects. Successful execution with `PATH=/nonexistent` verifies this property.

## RED/GREEN and commands

All unittest commands below ran from `axiom/`.

1. Tests were written before changing production code. The initial test run exposed test construction errors: `Limits` itself rejects invalid constructor arguments, and this runtime did not emit opcode tracing events. The tests were corrected to supply a hostile limits namespace and count executed lines containing formatting opcodes. No production code had changed.
2. RED: `PYTHONPATH=src python -m unittest tests.test_validation_hotpath -v` ran 5 tests with exactly 2 intended failures: valid records called `_integer` 22 times (required at most 2) and executed 17 eager diagnostic-formatting lines (required zero). All three differential tests passed against the old implementation.
3. GREEN after production change: `PYTHONPATH=src python -m unittest tests.test_validation_hotpath tests.test_codec -v` passed 23 tests, 2.244 seconds.
4. Focused checker/selection integration command below passed 91 tests, 3.194 seconds:

```sh
PYTHONPATH=src python - <<'PY'
import unittest
names = ['tests.test_validation_hotpath', 'tests.test_codec', 'tests.test_checker',
         'tests.test_selection', 'tests.test_compilation_selection.RankedSelectionTests']
excluded = 'tests.test_selection.SelectionTests.test_every_admitted_shape_and_cap_boundary_against_analytic_portfolio'
def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        elif item.id() != excluded:
            yield item
suite = unittest.TestSuite(cases(unittest.defaultTestLoader.loadTestsFromNames(names)))
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(not result.wasSuccessful())
PY
```

5. `PYTHONPATH=src python -O -m unittest tests.test_validation_hotpath tests.test_codec -q` passed 23 tests, 2.029 seconds.
6. After adding two-operation/comma byte-boundary coverage, `PYTHONPATH=src python -m unittest tests.test_validation_hotpath tests.test_codec -q` passed 23 tests, 2.256 seconds.
7. `PATH=/nonexistent PYTHONPATH=src /opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python -m unittest tests.test_validation_hotpath -q` passed 5 tests, 0.099 seconds.
8. From repository root, `git diff --check -- axiom/src/axiom/codec.py axiom/tests/test_validation_hotpath.py axiom/tests/fixtures/codec-21f36d4.py.txt` passed.

An earlier invocation, `PYTHONPATH=src python -m unittest tests.test_validation_hotpath tests.test_codec tests.test_checker tests.test_selection tests.test_compilation_selection.RankedSelectionTests -q`, accidentally included the existing 955-shape selection sweep. It was interrupted with SIGINT to honor the brief's no-large-sweeps constraint. The selector treats interruption as incumbent preservation, so that interrupted run finished with 92 tests / 1 failure in `tests.test_selection.SelectionTests.test_every_admitted_shape_and_cap_boundary_against_analytic_portfolio` (`inline-v1` versus `rows2-v1`), 46.476 seconds. This is not reported as a passing run or as an independently reproduced regression. The complete focused rerun above explicitly excludes that sweep and passes. Final full-suite/qualification runs remain assigned to the coordinator by the brief.

## Coverage

The new tests compare exact rejection code, field path, and complete exception string to the immutable baseline for malformed direct records across all seven opcode shapes; bool/null/string/float/out-of-range fields; operand arity and nonprior SSA; dense destinations; reserved scratch indices; invalid literals and origins; invalid Unicode labels; invalid limits; operation quotas; and byte-quota/error precedence. Empty, one-operation, and two-operation plans exercise every positive byte budget through and just beyond the two-operation canonical size, including partial origin-digit quota charges and commas. All opcode shapes and three actual generated candidates compare complete actual metrics and exact encoded bytes. The deterministic hot-path checks assert zero executed diagnostic-formatting lines and at most two generic integer-helper calls, without timing thresholds.

## Single diagnostic profile

This command ran once, after plans were generated:

```sh
PYTHONPATH=src python - <<'PY'
import cProfile
from axiom import codec, planner
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from tests.helpers import stencil_source
from tests.test_validation_hotpath import ValidationHotpathTests
ValidationHotpathTests.setUpClass()
kernel = admit_source(parse_source(stencil_source(15, 15, None)))
plans = [planner.make_plan(kernel, label) for label in planner.PLAN_IDS]
for name, module in [('prior', ValidationHotpathTests.prior), ('current', codec)]:
    with cProfile.Profile() as profile:
        metrics = [module._validate_plan(plan, Limits()) for plan in plans]
    integer_calls = sum(entry.callcount for entry in profile.getstats()
                        if entry.code is module._integer.__code__)
    validation = next(entry for entry in profile.getstats()
                      if entry.code is module._validate_plan.__code__)
    print(name, 'operations=', sum(len(plan.operations) for plan in plans),
          'metrics=', metrics, 'integer_calls=', integer_calls,
          'scan_profile_seconds=', round(validation.totaltime, 6))
PY
```

Both versions scanned 9,251 actual operations and returned `[(900, 0), (256, 128), (256, 1024)]`. Generic integer calls fell from 32,608 to 6. Profiled cumulative validation time was 0.055242 seconds before and 0.038143 seconds after. These single-run native measurements are diagnostic observations, not browser qualification or timing assertions.

## Self-review

Reviewed every changed quota checkpoint and integer error message against the frozen codec. Shell accounting, minimum-origin precharge, per-origin digit increments, bool rejection, SSA order, scratch reservation checks, and metric-return placement match. The production diff contains no canonical serializer changes. Added duplication consists only of the deliberately immutable test oracle; no production duplicate or export uses it. Neighboring source-facts and correspondence work was left to its owners.
