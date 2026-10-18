# Independent runtime and service review

Review date: 2026-10-18. Scope: the new checked interpreter, demo service, and their tests in `runtime-review.diff`, against `docs/superpowers/specs/2026-10-18-axiom-presentation-design.md`. Existing source admission, plan codec/checker, and selection are trusted dependencies; their relevant contracts were inspected to verify the new callers. No repository files were changed and no full test suite was rerun.

## Verdicts

- **Spec compliance: substantially passes, with one low-severity diagnostic-offset deviation below.** The central execution, snapshot, selection, and complete-comparison requirements are satisfied.
- **Code quality: approved with a small correction requested.** No high- or medium-severity findings. The implementation is compact, uses the existing compiler, and keeps its finite v1 interpretation and logical scratch claims accurate. Fix R1 and add its focused regression case before declaring the diagnostic contract fully met.

## Finding R1 — Low: invalid source encoding reports a character offset as a byte offset

Location: `axiom/src/axiom/playground_service.py:72` (the `Span(error.start, ...)` construction).

`UnicodeEncodeError.start` is an index into a Python Unicode string. The service places that value in the response's `diagnostic.offset`, whose contract and `DiagnosticError` documentation define offsets in UTF-8 bytes. A non-ASCII valid prefix makes the returned offset incorrect.

Focused reproduction, executed successfully from the repository root with `PYTHONPATH=axiom/src`:

```python
from axiom.playground_service import run_demo
source = 'λ\ud800'
print(run_demo({'source': source, 'input_mode': 'ramp'}))
print(len(source[:1].encode('utf-8')))
```

Observed diagnostic: `INVALID_SOURCE_ENCODING`, offset **1**. The valid prefix occupies **2** UTF-8 bytes. This concerns direct `run_demo` requests; the strict stdin JSON decoder rejects surrogate strings before this service path. Execution remains fail-closed and no output is exposed.

Recommended correction: compute the start offset from the UTF-8 byte length of the valid prefix, `len(text[:error.start].encode('utf-8'))`. Define a sensible zero-width span at the unencodable position (or another explicit invalid-encoding convention); do not reuse character counts as byte lengths. Add a regression test with a multibyte prefix before a surrogate. This does not require changing the trusted source parser.

## Confirmed contracts

- `runtime.py:41-51`: exact immutable source and plan byte arguments; source is parsed/admitted, supplied plan bytes are decoded, and that resulting immutable plan is freshly checked before interpretation. Unknown, invalid, and constraint-violating checks cannot execute. There is no unchecked public interpreter function or saved check argument.
- `runtime.py:18-29,53-62`: exact list/tuple boundary, exact integer scalars (including boolean rejection), i32 and extent checks, identity alias rejection, independent snapshots, and complete boundary validation before source-precondition evaluation. A failed precondition returns the complete initialized output and the first row-major invalid input; the caller buffers are never assigned into.
- `runtime.py:64-98`: execution walks the checked physical operation stream and computes values independently of the source evaluator. Every value-producing operation receives a runtime exact-i32 check. Scratch stores/loads use a sparse dictionary, output is private, and returned observations contain immutable tuples.
- Sparse scratch storage preserves the admitted physical indices and overwrite/read semantics while allocating only for touched cells. The declared arena remains the logical `plan_workspace_bytes` metric; the module accurately disclaims equivalence with Python heap usage.
- `playground_service.py:92-125`: the current source determines shape, cap, objective, and inputs; the existing portfolio receives the fixed 100000 selection budget. The selected artifact bytes are passed through the fresh runtime boundary, and the original parsed source is evaluated separately.
- `playground_service.py:126-133`: dataclass equality compares status, first failure index, all output cells, and all input observations. A disagreement returns only an error object, so a mismatch cannot become a success. `cells_compared` counts output cells, matching the implementer report's root clarification.
- `playground_service.py:55-89,137-161`: exact request fields and input modes, bounded source handling and finite admitted dimensions, stable structured service errors, bounded strict JSON worker input (131072 bytes, 512 members/elements, depth 4), and no user-supplied plans, commands, or paths. The 10-second process timeout and HTTP boundary belong to the separately reviewed server integration.
- The three bundled examples and response fields implement the stated finite-v1 presentation contract. No native execution, scalable-v2 completion, or qualification claim is introduced.

## Evidence and limits

The implementation/test file SHA-256 identities match `runtime-report.md`:

- `runtime.py`: `54d35cd52e4ad19944ea4f0807ccadac7ef999a0c635e4776cd2ea111308b71b`
- `playground_service.py`: `c526aefdb3ecc8f8a5b81f46ea49022dadbf365f638af89783636e78aea47aa9`
- `test_runtime.py`: `33a71e05c3fbaa724abbba3a8d5b16807db39392692c38e362dafaceedc23e7f`
- `test_playground_service.py`: `9b307a0966ce644a75f2b082be13a682eca373e173e80d9e16681e01fc0405f9`

Read and checked the implementer's normal and optimized logs: each reports **24 tests passed** (3.350s normal, 3.362s optimized). Test code covers all schedules, maximum admitted shape, altered bytes, wrong source, unknown/ineligible checks, caller preservation, boundary errors, unused huge scratch reservations, selection metrics, observation mismatches, and real worker execution. These are implementer-run results, not independent suite reruns. The only independent execution in this review was the focused R1 reproduction above. The interrupted product log is not treated as regression evidence. Root owns full integrated testing, HTTP/browser review, and integration.

## Scoped R1 recheck — 2026-10-18

R1 is resolved. The service now catches `UnicodeEncodeError`, computes `len(text[:error.start].encode('utf-8'))`, and uses a zero-width span at that byte boundary. The new regression exercises empty, ASCII, Greek, and mixed Greek/emoji valid prefixes before a surrogate; it also verifies that rejected requests expose no output.

Independently ran only `tests.test_playground_service.PlaygroundServiceTests.test_invalid_unicode_diagnostic_uses_utf8_prefix_byte_offset` from `axiom/` with `PYTHONPATH=src`, once under normal Python and once under `python -O`: each ran 1 test and passed. No broad suite was repeated. Final scoped verdict: **SPEC PASS / QUALITY APPROVED**, with no remaining runtime/service findings. Full integration remains root-owned.
