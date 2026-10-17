# External evaluator export v1

This adapter validates **synthetic infrastructure fixtures only**. Native
eligibility is always unavailable. Neither JSON fields, an eligible-looking
local result, nor the external evaluator's decision can enable native
collection, establish physical instrumentation, widen Plan01's supported
profile, or authorize adoption.

`admit_export(request, experiment, python, evaluator, limits)` creates an
`ExportAdmission` containing the full source closure and a retained snapshot.
`evaluate(admission, request, python, evaluator, output)` freshly admits both
source and retained bytes before and after invoking the external evaluator.
Failures raise `ValueError` (filesystem/subprocess failures may propagate).
Caller-owned result and receipt paths must not exist. Successful execution
returns an `EvaluationRun`; its result preserves the evaluator's decision and
its `native_eligible` remains false. A nonzero evaluator exit is retained as an
unsuccessful run, never converted to eligibility. A failed pre/post revalidation
raises instead of creating an adapter run receipt; any evaluator output left by
that failed run is not admitted evidence.

## Independent export envelope

The exact-schema JSON file `<request filename>.axiom-export.json` lives beside
the evaluator request. All paths in this envelope, evaluator references and
measurement receipts use normalized relative POSIX spelling, relative to that
shared evidence root. No absolute paths, traversal, symlinks, special files or
`.tools` path components at the root are accepted. State chunk and acquisition
references retain their state-manifest-relative semantics. The whole evidence
root must be self-contained; unrelated files are not admitted or copied.

The envelope has exactly these fields:

- `schema`: `axiom-export-v1`.
- `profile`: `synthetic_correctness_fixture` or
  `synthetic_descriptive_held_out_fixture`.
- `verifier_version`: `axiom-export-v1.0`.
- `request`, `experiment`, `semantic_contract`: `{path, sha256}` references.
- `oracle`: `{expected_manifest: {path, sha256}, sidecar: {path, sha256}, version}`.
- `python_sha256`, `evaluator_sha256`: exact tool bytes.
- `measurements`: a bijection of
  `{measurement: {path, sha256}, receipt: {path, sha256}}` for every pilot and
  evaluation run. Duplicate, missing, reused and extra mappings fail.

The fixture author must select and pin the expected manifest and oracle sidecar
**independently of all measurement claims**, in this separate envelope. An
untrusted party cannot establish oracle independence by rewriting its own
envelope and declaring itself independent. Envelope review/selection is an
explicit fixture-author trust boundary. The adapter checks consistency with
this selected fixture; it does not derive a trusted oracle from a receipt's
self-claimed expected digest. Synthetic expected values are test data, never a
reviewed scalable source oracle. The test fixture's four-neighbor arithmetic
lives only in the tests and imports no planner, emitter or collector logic.

## Profiles and mapping

The correctness profile maps a frozen `correctness` workload to evaluator
`role: selection`. Its A/A pilot is evaluator machinery, represented by
correctness receipts after the research policy freeze. A/A positions both bind
the baseline artifact. Its separate historical synthetic evaluator freeze must
follow the research policy freeze. It does not claim the primary experiment's
full pilot/held-out chronology gate. Known held-out content and, under a shape
holdout policy, held-out shapes cannot be disguised as correctness fixtures.

The descriptive held-out profile requires an actually approved frozen held-out
stratum and matching baseline-A/A `pilot` declaration. Its evaluator policy
freeze equals the research manifest's policy freeze. Every measurement is
converted to a chronology receipt, alongside the external frozen selection;
`validate_chronology` must pass for the actual stratum. Selection timestamps use
whole UTC seconds. The primary stratum is unavailable in this adapter. The
8191×1 seed65537 test retains real approved LCG input bytes and independently
authored literal expected output, but remains synthetic and descriptive. The
frozen 2047×2049 seed65537 primary endpoint is preserved in the experiment.

Both profiles require all planned samples, exact frozen randomized order,
unit/session/measurement identities, pair positions, artifact identities,
compiler/toolchain/environment identities, exact UTC intervals, every paid
component/resource and raw receipt observation, and exactly one completed
successful semantic case per run. The independently admitted acquisition and
oracle compare complete input-after/output bytes and status. Mismapped metrics,
roles, state, events, stdout or any identity fail. No receipt-provided command is
executed; compiler argv remains evidence data.

Every block's evaluator independence method is also bound to the frozen
sampling mode. `fresh_owned_process` requires `separate_owned_sessions` and
unique session IDs across **all pilot and evaluation runs**, not just within a
pair or phase. `reset_contract` requires `verified_reset_equivalence`; the
external independence `evidence` must reference the exact same retained file as
both research receipts' `reset_evidence`, with its hash equal to the frozen
`reset_evidence_sha256`. Reused sessions are permitted only under this reset
mapping. A different proof file, including an equal-content path alias, does not
substitute for the selected shared evidence. The frozen reset protocol and all
receipt sampling settings still undergo ordinary receipt admission. This is
consistency with a fixture-author-selected synthetic reset contract; physical
reset effectiveness and sampling independence remain external assumptions.

The evaluator's `semantic.state` reference points directly to the canonical
observed state manifest. Acquisition and oracle sidecars stay outside the
unchanged evaluator exact schema. The evaluator sees this manifest as an opaque
equality object; it does not understand chunks. The external gate verifies all
chunks and compares observed and independently selected expected state. No
semantic digest shortcut replaces that comparison. The semantic contract is a
nonempty retained object whose exact identity is shared by the envelope and the
evaluator fingerprints; it is a declared synthetic assumption, not a proof of
source semantics.

## Pins, closure and execution

The pinned evaluator SHA-256 is
`b368462fc46c3173650c8654765e283fc84fd1e86c7c6c11154d809367956593`;
its Git blob identity is `2549df76055546a3b89d91cbc99599d2d131b96f`.
Both pins are checked before using its exact captured code bytes for analytical
validation. The evaluator itself is never modified. Its threshold remains
`max(5%, pilot p95 absolute paired variation)`; stale/changed freezes fail the
pinned evaluator's own recomputation. The adapter adds no pooled or multiple
comparison claim.

Closure includes request, envelope, experiment, all direct evaluator references,
all measurement receipts, observed and expected manifests/chunks, acquisition
and oracle sidecars, raw observations, semantic/diagnostic/reset/independence/
selection evidence, artifact identities and both executable tool files. Every
unique path counts once; equal bytes at distinct paths count separately. Limits
cannot exceed 16 MiB/file, 256 MiB aggregate or 16,384 files. Expanded logical
state length is separately summed over distinct state manifests, including both
observed and expected. Python executables larger than 16 MiB fail this same
bound; the tests select the available bounded `/usr/bin/python3` executable.

Snapshots preserve evidence-relative paths and copy tools into `.tools`.
Exclusive file creation and read-only modes prevent accidental replacement.
Full closure/semantic readmission is repeated on the retained copies and source
before and after execution. Caller-fabricated `ExportAdmission` objects provide
no authorization: their fields and closure must match fresh admission. This is
retained reproducible storage, **not an adversarial same-UID filesystem sandbox**;
a privileged writer can defeat permission modes or make transient changes.
Python's shared libraries/standard library and OS are execution-environment
assumptions, not claimed hermetic toolchain closure. These limitations cannot
open native eligibility.

The only evaluation argv is
`[retained_python, retained_evaluator, 'evaluate', '--input', retained_request,
'--output', new_output]`. Python startup environment injection is removed.
Python version is obtained with `[python, '--version']`; binary hash/version,
evaluator pins, verifier version, normalized closure, argv, exit status, result,
assumptions and unavailable native gates are written to
`<output>.axiom-run.json`. There is no invented `--now` argument. Analytical
historical freeze fixtures are explicitly synthetic inputs; a real `freeze`
CLI run uses the current clock. Repeated freeze timestamps need not be byte
identical. `selection_only`, `synthetic_gate_pass`, resource failures and
unsupported-threshold results retain their evaluator meaning; none constitutes
a native measurement or automatic adoption.
