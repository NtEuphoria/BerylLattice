# Runtime and service implementation evidence

Task1 implemented on `feat/axiom-presentation-demo`; no commits created by this agent.

## Implementation

- New `execute_plan` accepts exact source/plan bytes, freshly admits/decodes/checks, independently validates owned buffers, preflights all inputs, and interprets the seven physical opcodes with checked i32 arithmetic.
- No runtime calls to the source evaluator. Sparse scratch storage bounds allocation by touched operations even for a large unused declared reservation; reported scratch remains the logical declared arena metric, not Python heap usage.
- `run_demo` selects the actual portfolio, executes selected bytes, compares complete status/first-failure/input/output observations with the original-source evaluator, and emits schema1 JSON. `comparison.cells_compared` counts output cells only, per root clarification; all input cells are still compared.
- `get_examples` returns three complete literal sources. Worker mode reads one bounded strict JSON stdin request, emits one JSON line, and exposes no commands or paths. Imports avoid filesystem/evidence/Core/research modules for browser compatibility.

## Test-first evidence

1. Added behavioral runtime and service tests before production modules existed.
2. `PYTHONPATH=src python -m unittest tests.test_runtime tests.test_playground_service -v` -> exit1;24 test methods,72 subtest failures asserting the required production modules were missing; no errors. Log: `runtime-red.log`.
3. Implemented modules. Same command -> exit0,24 tests passed (initial3.630s).
4. Root clarified comparison count means output cells. Changed three behavioral expectations first. Focused run -> exit1,3 failures (83vs35 /481vs225). Log: `runtime-count-red.log`.
5. Updated count and reran full focused set. Normal: exit0,24 tests passed,3.350s (`runtime-green.log`). Optimized: exit0,24 tests passed,3.362s (`runtime-optimized.log`).

Commands run from `axiom/`:

```sh
PYTHONPATH=src python -m unittest tests.test_runtime tests.test_playground_service -v
PYTHONPATH=src python -O -m unittest tests.test_runtime tests.test_playground_service -v
```

Coverage includes all three schedules, coordinate-sensitive input,15x15 max balanced shape, altered plan arithmetic, wrong source identity, malformed bytes, cap violations, unknown budget results, every preflight position, caller-buffer preservation, exact type/extent/i32/alias checks, huge unused scratch declarations, malformed/unsupported/oversized source, exact request schema, three input patterns/custom data, injected final-output/input/status mismatches, no eligible incumbent, and real stdin worker plus malformed/duplicate/oversized JSON.

`git diff --check` passed. A full product run was started just before root requested deferring it until HTTP/UI integration, then interrupted by SIGINT only after verifying its exact argv and stdout-log descriptor; exit130. `runtime-product.log` is incomplete and does not establish suite success. Root owns the final integrated product/research checks and independent review.

## Source identities

- `axiom/src/axiom/runtime.py`: `54d35cd52e4ad19944ea4f0807ccadac7ef999a0c635e4776cd2ea111308b71b`
- `axiom/src/axiom/playground_service.py`: `c526aefdb3ecc8f8a5b81f46ea49022dadbf365f638af89783636e78aea47aa9`
- `axiom/tests/test_runtime.py`: `33a71e05c3fbaa724abbba3a8d5b16807db39392692c38e362dafaceedc23e7f`
- `axiom/tests/test_playground_service.py`: `9b307a0966ce644a75f2b082be13a682eca373e173e80d9e16681e01fc0405f9`

## Evidence identities

- `runtime-red.log`: `c32f95e452a422fe830298524882dcb65fe4947ddcbe2440e7d063068f96666b`
- `runtime-count-red.log`: `a25d6d44bb579cec645ae8f0fb9bc3ecc4d3543987c7477b083d6a3b9e73b47b`
- `runtime-green.log`: `e3daa0d363650e408a4da45c732bcadc5191ecb8c836adb5cd077673f736a29c`
- `runtime-optimized.log`: `5bc11c968aee625143fe0fd3f3c201728eb862c44a9f1f2c99781a418fe49191`
- `runtime-product.log`: `420a8cd50b18f61e3cd7c3dd19d6b43d49f18173c4f42b90cd428ebdec90ef71`

## Independent review follow-up: UTF-8 diagnostic offsets

Reviewer identified that `UnicodeEncodeError.start` counts Unicode characters while the API diagnostic offset counts UTF-8 bytes. Reproduced with a new regression before editing implementation: source `λ\ud800` reported1 instead of2; source `aλ🙂\ud800` reported3 instead of7. Empty and ASCII prefixes remained controls. Focused RED: exit1,1 test method/2 subtest failures (`runtime-unicode-red.log`).

Changed `_request_source` to encode the valid prefix and use its byte length, with a zero-width span at the invalid character boundary (an invalid surrogate has no UTF-8 encoded width). No other behavior changed.

Fresh focused verification:

- Normal: `PYTHONPATH=src python -m unittest tests.test_runtime tests.test_playground_service -v` -> exit0,25 tests,3.802s.
- Optimized: `PYTHONPATH=src python -O -m unittest tests.test_runtime tests.test_playground_service -v` -> exit0,25 tests,3.750s.
- Scoped `git diff --check` passed.
- No full suite run and no commit during this follow-up.

Updated implementation/test identities (supersede earlier values for these files):

- `axiom/src/axiom/playground_service.py`: `562dc076bd787641804af4cab8a7b8b691bb7f51d5fbed2d33751118d654eb23`
- `axiom/tests/test_playground_service.py`: `dc3ab0ff109486ed572c64fc8f7a8cbb22546cb697b7686c12a2e92e8285aaeb`

Follow-up evidence identities:

- `runtime-unicode-red.log`: `822b6406cc39477f94e6a4bc249aeabd8ebed6f07ede8fc7b5cb747604b70bce`
- `runtime-unicode-green.log`: `f47908d38b9fdb83d6f2d1ec45df7710b3724125b6631b3949d3790fad7f6b93`
- `runtime-unicode-optimized.log`: `74762c4defe46b1b1e2e04aa6614faf7cfd1367075bb7828c37a667634405e4e`
