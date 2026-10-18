# Task 5: compact native C

Status: DONE_WITH_CONCERNS (backend implementation verified; paired latency, compiler phase and throughput qualification remains with coordinator).

## Implementation

- Added `axiom/src/axiom/bounded_loop_c.py` with `_emit_native_c_compact(owned, hint_bytes, *, hint_limits=HintLimits()) -> NativeArtifact`.
- Requires exact live owned check before any correspondence work. Freshly calls `validate_loop_correspondence` on each emission, in the same call consuming its validated structured program. Caller-created correspondence records are never emission authority.
- Emits lexical counted loops, lexical scalars and all seven primitive kinds in their actual order, including dead operations. No schedule-ID recognition or stencil formula substitution.
- Add/multiply and each ordered index offset/multiply/accumulation widen before arithmetic to int64, then convert under fresh finite proof/correspondence checks. Modulo-two uses uint32 parity, including negative components. Decoder separately bounds loop starts/stops to 0..256, so increments cannot overflow.
- Shared `_native_kernel_parts` and `_finish_native` reuse headers, full row-major preflight, scratch allocation, exact dimensions and bounded-token standalone driver. No whole-backend copy.
- `NativeArtifact` appended default-compatible `codegen_version`, `hint_digest`, `loop_version`. Compact codegen version is `beryl-bounded-loop-c-v1`; raw hint SHA256 and correspondence version bind intent. Raw source/plan byte identities remain owned checked identities. Finite metadata defaults to `beryl-finite-c-v1` without changing finite C bytes.
- Trace phases: `loop_correspondence`, `code_emission`; counts: `loop_correspondences`, `loop_correspondence_work`, `code_emissions`.
- Current optimization policy unchanged; compact execution tests explicitly compile `-O3`.

## Tests first: RED/GREEN

Initial RED:

```sh
AXIOM_TEST_NATIVE_CLANG=/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_c.CompactCTest.test_source_reduction_at_15_by_15
```

Result before implementation: 1 test, ERROR `ModuleNotFoundError: No module named 'axiom.bounded_loop_c'`.

A preliminary run without `AXIOM_TEST_NATIVE_CLANG` skipped for missing PATH Clang; that was not counted as RED. During initial broader validation a test oracle field name was corrected from `first_invalid_input` to existing `first_bad_index`; no backend failure was hidden.

Final GREEN:

```sh
AXIOM_TEST_NATIVE_CLANG=/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_c tests.test_native_codegen
```

Result: 17 tests passed in 7.040s. Real compact libraries and drivers use C11 `-O3 -Wall -Wextra -Werror`; existing finite execution tests use their unchanged `-O2`.

New tests compare complete status/input/output observations with both original-AST evaluator and separately implemented finite interpreter, across all schedules and `(1,1),(1,127),(127,1),(3,4),(15,15)`. They cover repeated changing inputs, all-zero/all-upper-bound/asymmetric data, input/output arena canaries, poisoned scratch plus scratch canaries, output endpoint sentinels, multiple invalid inputs/first failure, exact driver dimensions, malformed/missing/extra/overflow/NUL/long tokens, negative modulo components, intermediate overflow despite normalized in-range final index, hostile hint types/quotas, changed labels, forged/replaced/cross-owner/closed ownership, fresh correspondence each time, trace counts, arbitrary appended dead signed endpoint operations and missing-dead-operation mismatch. Rehashed faulty C that omits a store, redirects an output index or refills rolling rows early compiles successfully and is rejected by independent execution observations.

A separate pre-refactor/post-refactor byte comparison confirmed all 9 finite C SHA256 values unchanged for 1x1/3x4/15x15 times all schedules. `git diff --check` passed.

## Source size evidence (15x15)

| Schedule | Finite C bytes | Compact C bytes | Reduction |
| --- | ---: | ---: | ---: |
| inline-v1 | 302336 | 7139 | 42.35x |
| rows2-v1 | 200517 | 11579 | 17.32x |
| materialize-v1 | 201432 | 7695 | 26.18x |

The >=10x source reduction target passes for all schedules. This is not a cold latency qualification.

## Limitations / coordinator follow-up

- No timing sweeps were run while other agents test, as instructed. Coordinator must measure paired cold build, Clang frontend/optimizer/codegen trace, IR/object bytes, full link latency and kernel throughput. Clang may re-unroll constant loops; no flags were changed without evidence.
- Generic arbitrary finite-plan fallback remains straight-stream emission. Existing finite tests prove arbitrary extended plans execute; source-compilation coordinator owns hint miss/typed-error fallback wiring and its end-to-end tests.
- Native raw pointer API retains documented exclusively owned disjoint initialized-array contract. It cannot dynamically prove caller ownership.
- No full production suite run by this agent; final integration owns it.

## Self-review

Reviewed lexical scope/name separation, scalar definition order, scratch stage/consume/refill lifetime, zero-trip loops, index widening/parity, array count boundary, preflight before all writes, raw identities, malformed driver paths, artifact compatibility and unchanged finite byte emission. Independent review is still scheduled by coordinator.

## Commit

Commit: `a372dd8` (`Add freshly matched lexical compact C backend`). This local report stays under ignored `.superpowers` task evidence.

## Review follow-up: zero-trip unreachable arenas

Independent review of `a372dd8` found an accepted zero-trip loop whose unreachable scratch load was emitted despite zero scratch reservation. Clang must resolve identifiers before optimization, so it rejected the generated program for undeclared `scratch` even though correspondence expansion correctly contained no operations from that loop.

Fixed compact lowering to omit loops with equal validated start/stop bounds. This branch executes only after fresh complete hint decoding, syntax/scope validation and finite correspondence checking; it skips no reached primitive, including semantically dead finite operations. No other modules or flags changed.

Added `test_zero_trip_loops_with_unreachable_arena_operations_compile`. Under zero scratch reservation it appends zero-trip loops at bounds 0 and 256 containing all arena operation kinds (input load, scratch load/store, output store), nested loops and unreached negative/out-of-range/overflowing indices. Actual strict Clang compilation and callable status/input/output observations match original AST and finite interpreter for valid and invalid data. Emitted C remains identical to the original matching finite stream while raw hint identity still differs. A malformed unreachable scope remains rejected by fresh validation.

RED command:

```sh
AXIOM_TEST_NATIVE_CLANG=/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_c.CompactCTest.test_zero_trip_loops_with_unreachable_arena_operations_compile
```

Before fix: 1 test, 2 subtest failures; real Clang reported undeclared `scratch` at both zero bounds. After fix: 1 test passed in 0.252s.

Covering GREEN command:

```sh
AXIOM_TEST_NATIVE_CLANG=/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang PYTHONPATH=axiom/src:axiom python -m unittest tests.test_bounded_loop_c tests.test_native_codegen
```

Result: 18 tests passed in 7.330s. This includes actual Clang compilation, all boundary schedule observations, rehashed emitter faults and existing dead signed-i32 operation semantics. `git diff --check` passed. Follow-up commit is recorded below after creation; scoped independent rereview remains with coordinator.

Follow-up commit: `f71e12d` (`Omit freshly validated zero-trip C loop bodies`).
