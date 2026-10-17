# Axiom correctness prototype

Axiom admits one declarative two-stage stencil. For positive fixed H and W with
`(H+1)*(W+1) <= 256`, its input is `[H+1,W+1]`, its output is `[H,W]`, and
`p[r,c]=(image[r,c]+1)*(image[r,c]+1)`. Each output adds its four neighboring
producer values in the grouping shown in [the example](../examples/stencil.ax).
Input values are integers in `[0,1023]`; every scalar node uses exact i32
arithmetic. Valid output values lie in `[4,4194304]`.

Python 3.12 or newer and the standard library are sufficient. Publication uses
POSIX directory descriptors and no-follow file opens, as available on this Linux
cloud environment; output directories and their ancestors must be real
directories rather than symlinks. This milestone
produces checked finite physical plans and replay receipts. It makes no native
ABI, compiler throughput, latency, energy, or speedup claim.

## Supported source and independent evaluation

The frontend accepts one UTF-8 file up to 65,536 bytes, ASCII identifiers,
whitespace and `//` comments. It rejects invalid UTF-8 and NUL. Diagnostics use
original UTF-8 byte offsets, including after non-ASCII comments. Integer tokens
have at most ten decimal digits; expression nesting is limited to 32.

Only H/W shape declarations, one input, one producer, and one output matching
the canonical stencil are admitted. Names and bound-axis names may vary;
alpha-normalization resolves their roles. Addition/multiplication grouping is
retained. Parenthesis wrappers do not change admission. General DAG lowering,
algebraic equivalence, imports, strings, macros, and source execution during
parsing are outside this profile. A well-formed different profile is unsupported;
syntax, undefined-read, duplicate-name, and nonpositive-shape errors are invalid.

`require plan_workspace_bytes <= N` is optional, with `0 <= N <= 2147483647`.
Unknown hard properties are unsupported. Optional `prefer multiplication_ops`
(the default) or `prefer plan_workspace_bytes` chooses an abstract ranking.
A semantic hash covers normalized equations, shapes, i32 arithmetic and boundary
assumptions. Names, formatting, constraints, and ranking have separate identities.
Source-origin IDs and spans are diagnostic provenance labels; they do not prove
semantics. Plan IDs are stable ranking labels and provide no checker privilege.

`eval` interprets the retained original source AST after admission. Its evaluator
imports neither the physical planner nor its checker or a Core emitter. The
Python `evaluate_source` API consumes a parser-produced `SourceModule`; it
trusts that module's AST as the source program. It does not authenticate a
caller-constructed AST against separately supplied source bytes or digest
fields. The CLI parses the supplied bytes, and the checking, publication and
Core emission boundaries independently bind their exact source snapshots.
Direct callers must use `parse_source` when source-byte identity matters.
The public boundary accepts owned Python tuples/lists of the exact lengths, requires
disjoint input/output and stable input, and scans input in row-major order before
any scalar computation. The first value outside `[0,1023]` produces
`input_precondition_failed`, the first invalid linear index, the complete
unchanged initial output, and unchanged input. It does not certify foreign memory.
Shape/type/non-i32 boundary errors are invalid input diagnostics.

## Physical plans, checker, and selection

Physical format 1 is a finite unrolled stream of `const`, `input_load`, `add`,
`mul`, `scratch_store`, `scratch_load`, and `output_store` operations. It has dense
ordered SSA definitions, constant indices, and one separate i32 scratch arena.
The independent checker validates the actual stream, initialization, output
coverage, ranges, and expression structure against separately reconstructed
source expressions. A structurally different expression without a concrete
counterexample is unknown. No solver or algebraic rewrite establishes validity.

`plan_workspace_bytes = 4 * scratch_capacity_cells`, including unused reserved
cells. SSA values, registers, spills, input/output, and backend memory are
excluded. `multiplication_ops` counts every `mul` opcode, including dead work.
The SSA-staged adversarial positive control can compute all producers once in
retained SSA values with zero scratch; it exposes this resource contract's
limitation. It is checker-admissible and outside the fixed selector portfolio.

The selector checks `inline-v1`, `rows2-v1`, then `materialize-v1`. It ranks by
the requested metric, the other metric, then stable plan ID, using independently
eligible results only. Eligibility requires `check_complete`, semantic `valid`,
and constraint `satisfied`. H5/W7 under multiplication ranking selects inline at
cap0, rows2 at cap64, and rows2 without a cap. The latter uses 48 multiplications
and 64 scratch bytes; materialization has 48 multiplications and 192 scratch
bytes. Workspace ranking selects inline. These are portfolio comparisons, not
global optimality statements.

Default independent quotas are source bytes 65,536; plan bytes 2,097,152; physical
operations 20,000; expression nodes 100,000; and checker steps 100,000. A checker
step is charged before each expected-source AST-node visit, physical operation,
and node-pair comparison visit, even if conceptual visits are memoized. Parsing,
admission, decoding, hashing, allocation, and generation are outside this counter.
This accounting version is 1 and does not bound total compiler time.

`plan --check-steps N` supplies the total search allowance, including the first
inline candidate; each call also obeys the default per-call limit. Optional
`--optional-check-steps N` bounds further checking after an eligible initial
incumbent and consumes the same total allowance. Zero total establishes no
artifact; zero optional allowance stops after eligible inline. Later exhaustion
preserves a previous fully checked incumbent. Failure to establish eligibility
under a budget is not proof of constraint infeasibility. Complete metrics remain
null until a complete operation scan; progress and final proof are distinct.

## Evidence and exact replay

`write_attempt(directory, module, result)` independently re-admits the source,
validates frozen record types, retained bytes and budget context, then freshly
checks the selected plan before publication. A supplied `SearchResult` or
`CheckResult` success bit is not a proof. It writes content-addressed
`source-<sha256>.ax` and `plan-<sha256>.json` snapshots before atomically replacing
`manifest.json`. All creation, linking, cleanup, and replacement use a pinned directory
descriptor, so an ancestor swap cannot redirect writes to another directory.
The named directory identity is checked before and after manifest replacement.
Existing content files must match every byte and cannot be silently overwritten. Content files are fsynced, referenced snapshots are checked
again, and the directory is fsynced around final manifest replacement. An
interruption can leave complete unreferenced files; the previous manifest stays
usable before replacement. Arbitrary external mutation after publication is
detected on replay, rather than prevented by this filesystem protocol.

Canonical manifest schema 1 records exact source/plan SHA-256, semantic,
constraint and ranking digests, semantics/plan/checker/accounting versions,
original cap, saved check, all attempt history, objective/key, termination,
independent limits and total/optional work accounting. The original cap is the
source cap; selection has no additional cap. A no-eligible manifest retains
source and history with null plan filename, plan digest, saved selected check,
and selected key. Its artifact state is `none`.

Replay manifest decoding rejects duplicate or unknown fields, noncanonical JSON,
floats, oversized integer tokens, incorrect exact types (including booleans in
integer fields), unsupported identities, and path changes. Its independent
quotas are 262,144 bytes, 4,096 container items, depth12, three attempts, 32 witness
pairs, at most seven opcode-count pairs, 256-byte labels/identities, 2,048-byte
reasons/witness text, ten-digit nonnegative accounting values and positive limits.
Caps have the source's i32 maximum. JSON records are immutable typed records
when decoded; saved checks and history never establish eligibility.

`replay(source, plan_bytes, manifest_bytes, limits, cap)` verifies exact retained
bytes and supported identities, requires the exact plan snapshot to use canonical
plan encoding, re-admits source and freshly calls the checker. Thus every accepted
fresh receipt identifies the exact supplied plan bytes. General plan decoding
may still accept noncanonical JSON outside exact replay.
A whitespace-only edit fails exact replay even if a separate fresh check succeeds.
A saved unknown result is history and cannot block a later fresh valid result.
A stale saved valid result cannot bypass a new checker limit or additional cap.
The effective cap is the minimum supplied source/replay cap, treating absence as
unbounded. A null replay cap preserves the source cap. Source cap64 with replay
cap192 retains cap64; replay cap0 checks under cap0 and rejects rows2's arena.
The new checker result binds the new constraint digest. Replay checks one plan
and makes no selection-optimality claim; ranking-policy changes require selection.

The CLI also verifies all source/plan snapshots referenced beside the manifest
before returning an accepted result, even if command arguments name other copies.
The bytes-only API has no filesystem context; callers managing published files
can additionally use `verify_references`. SHA-256 is traceability, not a semantic
proof, signature, or defense against arbitrary filesystem writers.

## Commands

Run from the `axiom/` directory. Commands emit one JSON result (help emits normal
usage text). No command evaluates source, paths or artifact contents as shell code.

```bash
PYTHONPATH=src python -m axiom check examples/stencil.ax
PYTHONPATH=src python -m axiom plan examples/stencil.ax --out /tmp/axiom-attempt --check-steps 100000
PYTHONPATH=src python -m axiom plan examples/stencil.ax --out /tmp/axiom-inline --check-steps 100000 --optional-check-steps 0
```

Read the recorded plan filename and invoke exact replay without a shell:

```bash
PYTHONPATH=src python - <<'PY'
import json
from pathlib import Path
import subprocess
import sys
root = Path('/tmp/axiom-attempt')
manifest = root / 'manifest.json'
record = json.loads(manifest.read_bytes())
subprocess.run([sys.executable, '-m', 'axiom', 'replay', 'examples/stencil.ax',
                str(root / record['plan_file']), '--manifest', str(manifest)], check=True)
PY
```

Add `--cap 0` to replay to tighten the arena requirement; that command exits4.
For source evaluation, create explicit input and initial-output JSON arrays:

```bash
python - <<'PY'
import json
from pathlib import Path
Path('/tmp/axiom-input.json').write_text(json.dumps([0] * 48))
Path('/tmp/axiom-output.json').write_text(json.dumps([-9] * 35))
PY
PYTHONPATH=src python -m axiom eval examples/stencil.ax --input /tmp/axiom-input.json --output-initial /tmp/axiom-output.json
PYTHONPATH=src python -m unittest tests.test_evidence tests.test_cli -v
PYTHONPATH=src python -O -m unittest tests.test_evidence tests.test_cli -v
```

| Exit | Meaning |
|---|---|
| 0 | Completed source admission, eligible plan/replay, or successful evaluation |
| 2 | Invalid input/source/artifact or CLI usage |
| 3 | Unsupported source profile/constraint or replay identity/version/policy |
| 4 | No eligible plan established, replay ineligible, or no recorded artifact |
| 5 | Infrastructure failure, missing referenced file, or interrupted operation |
| 6 | Runtime input precondition rejected with output preserved |

## Trust and limitations

The valid-input body obligation and boundary-wrapper obligation are separate:
physical checking proves no runtime preflight behavior because format1 has no
preflight operations. The composed checked entry needs both. The trusted base
comprises frontend parsing/admission and semantic normalization, the original-AST
reference evaluator and boundary validation, physical structural decoding and
validation, symbolic checking/range reasoning/exact comparison/work accounting,
constraint and eligibility predicates, canonical serialization/hash binding,
replay/publication checks, CLI routing, Python/standard-library execution and the
host filesystem's stated atomic replacement/fsync behavior. Tests and their
independent oracle support this argument and are not a formal proof. The planner
is outside the semantic checker trust boundary; selection is trusted only for
portfolio ordering, budgets and ranking, never for a candidate's semantics.

No native executable, foreign-memory guarantee, proof-cache reuse, incremental
edit reuse, runtime autotuning, learned model, general scalable-loop IR, public
unchecked execution entry, or release/publication is part of this prototype.
Core witnesses and conformance orchestration have separate workflows; these
commands do not imply their admission or results.
