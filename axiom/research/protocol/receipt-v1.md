# Measurement receipt v1

`receipt_admission.py` is an external consistency gate for one measurement. It
collects no timing, runs no compiler or receipt-specified command, and does not
admit an evaluator request or establish measurement honesty. Native admission is
unconditionally unavailable. No public JSON bit, collector/version string,
resource scalar or synthetic result can enable it. Separately reviewed collector
definitions and instrumentation, an independent scalable Axiom oracle, and the
larger-buffer lowering gate remain deferred.

`admit_measurement(receipt, experiment)` always returns `eligible=False`.
`admit_synthetic_fixture(receipt, experiment, fixture_oracle=...)` can return
`synthetic_eligible=True`; its `eligible` remains false and provenance remains
`synthetic`. This means the synthetic infrastructure checks passed. It is not
native execution, instrumentation validation, a performance observation, a
speedup, or evidence of the deferred gates. Returned `MeasurementAdmission`
records and their closure, reasons and assumptions are immutable.
`instrumentation_validated` is always false: retained raw observations can be
consistent without validating a physical measurement instrument.

## Strict records and identities

`MeasurementReceipt.to_record()` produces the v1 JSON record;
`MeasurementReceipt.from_record()` accepts exactly these fields, with strict
nested field sets. Read untrusted JSON with the bounded canonical JSON reader
before constructing typed records; reject duplicate keys. Arrays become immutable
tuples. Paths identify retained files; no path is executed. Transport/envelope
root confinement is the export adapter's additional responsibility.

Top-level fields are `schema_version` (integer 1), `provenance` (`synthetic` or
`native_observed`), `experiment_sha256`, `stratum_sha256`, `role`, `started_utc`,
`completed_utc`, `objective_sha256`, `selector_sha256`, `identity`, `state`,
`instrumentation` and `sampling`.

`identity` fields are `measurement_id`, `unit_id`, `session_id`, `run_sha256`,
`artifact_role` (`baseline` or `candidate`), `toolchain_sha256`,
`environment_sha256`, `compiler_argv` and `files`. IDs use the pinned evaluator's
1–128 ASCII letters/digits/underscore/period/colon/hyphen spelling. SHA identities
are lowercase SHA-256. `files` contains exactly one pair for each of `executable`,
`compiler`, `toolchain`, `environment`, `plan` and `emitted_kernel`. Each pair's
reference has exactly `path` and `sha256`. Retain actual executable/compiler bytes,
toolchain/environment descriptions, plan and emitted source, not version labels
as executable identities. The full compiler argv is retained; it is never run.
Compiler and selected binary hashes must equal the frozen experiment identities.
Toolchain/environment file hashes must equal the receipt's retained identities.
The evaluator request must additionally freeze and compare its environment and
toolchain fingerprints across measurements; one receipt cannot establish that
cross-measurement condition.

`state` fields are `observed_manifest`, `acquisition`, `expected_manifest`,
`oracle`, `events`, `stdout` and `diagnostics`. The final three are file
references. Actual acquisition must bind the observed manifest, invocation,
run, collector, plan, emitted kernel, executable, provenance and UTC window.
Expected state is independently bound by the oracle sidecar below. Both
manifests are verified through the state-artifact API, then compared scalar by
scalar, including complete observed post-call input, output, status and first
failing coordinate. Shape, logical semantics, original input and initial output
must match the frozen workload. Pair agreement or matching digests alone is not
a correctness oracle. The fully compared observed post-call input is also hashed
against the frozen original-input identity, so a fixture cannot redefine input
preservation by making both actual and expected post-call input equally wrong.
This extra invariant supplements the complete scalar comparison. Reusing a
pre-call/expected artifact without the observed
run's separate bound acquisition fails. Acquisition declarations cannot prove
that a physical collector actually observed those bytes.

## Instrumentation and raw observations

`instrumentation` fields are `collector_version`, `collector_sha256`, `raw`,
`timer_scope`, `start_ns`, `end_ns`, `included_phases`, `paid`, `total_paid_ns`,
`resources` and `diagnostics`. `raw` is a file reference. Timer scope is exactly
`checked_call`, with ordered integer monotonic boundaries inside the recorded UTC
window. Process duration is a separate diagnostic and cannot stand in for this
scope. The declared ordered phases are exactly `preflight`, `dispatch`,
`scratch_setup`, `initialization`, `copies`, `kernel`, `scratch_cleanup`.
They declare mandatory scope coverage; their presence in JSON does not prove
correct instrumentation. Preflight/dispatch/setup/initialization belong to
`setup`; required ABI/layout copies belong to `conversion`; kernel work belongs
to `compute`; scratch release belongs to `cleanup`.

Each observation has exactly `key`, `value`, `unit`, `scope`, `status`, `raw_key`
and `reason`. `reason` is always an exact string (empty is permitted except for
inapplicable costs); arrays, objects, booleans and null are rejected at observation
construction and parsing for every status. Its retained raw observation must
match value, unit, scope and
status exactly, including numeric type. Raw keys map one-to-one to paid,
resource and diagnostic observations, preventing one raw scalar from being
counted as two paid components. Required fields cannot be omitted.

`paid` has exactly `setup`, `capture`, `compute`, `maintenance`, `invalidation`,
`conversion`, `cleanup`, `cold_refresh`; units are `ns`, scope `checked_call`.
All values are nonnegative i63 integers. Their sum equals positive
`total_paid_ns` and fits the enclosing call interval. The collector must measure
disjoint costs actually paid by the operation. Zero has status `measured` with a
retained raw zero, or `inapplicable` with a nonempty reason and retained raw zero.
An unavailable cost has value `null` and is ineligible. No enclosing timer is
redistributed into invented stage values.

`resources` has exactly these required measured, nonnegative integer values:

| Key | Unit | Scope |
| --- | --- | --- |
| `peak_bytes` | `bytes` | `operation` |
| `retained_bytes` | `bytes` | `operation` |
| `allocations` | `count` | `operation` |
| `text_bytes` | `bytes` | `artifact_text_section` |
| `build_ns` | `ns` | `build` |
| `edit_check_ns` | `ns` | `edit_check` |

Retained bytes cannot exceed peak bytes. The exact native lifetime/allocator
contract has not been approved; these labels do not approve a collector. Do not
substitute RSS for allocator live/retained bytes, whole-file size for text-section
bytes, or logical arena capacity for measured physical memory. `diagnostics`
retains exactly `process_rss_peak_bytes` (`bytes`, `process`),
`arena_capacity_bytes` (`bytes`, `plan_arena`), and `allocator_peak_bytes`
(`bytes`, `allocator`). These three quantities remain distinct from the six
evaluator metrics. Unavailable diagnostics are explicitly `value:null`,
`status:unavailable`; unknown numeric values are never zero. Native admission
remains unavailable even if every scalar is supplied.

The retained raw document contains exactly `schema`, `measurement_id`,
`run_sha256`, `collector`, `identity`, `observations`, `timer` and `phases`.
Synthetic schema is `synthetic-instrument-observations-v1`; the unsupported
native consistency-only spelling is
`unreviewed-native-instrument-observations-v1`. Neither approves instrumentation.
`collector` is `{version,sha256}`; `identity` contains `files` (mapping each of the
six artifact keys to its hash), `compiler_argv`, `unit_id`, `session_id`, and
`artifact_role`. `timer` contains `scope`, `start_ns`, `end_ns`; `phases` matches
`included_phases`. `observations` maps each unique raw key to exactly
`{value,unit,scope,status}`. Keep instrumentation diagnostic text separate from
Axiom semantic `events` and `stdout`; Core internal trace offsets are not Axiom
semantic events.

## Sampling and chronology

`sampling` fields are `sample_index`, `pair_order`, `position`, `session_mode`,
`reset_evidence`, `schedule_sha256`, `reset_protocol`, `warmup`, `input_touch`
and `output_initialization`. Index and balanced `AB`/`BA` order must match the
frozen experiment sampling schedule; `position` is `A` for the baseline and `B`
for the candidate. A baseline A/A pilot uses baseline artifacts at both positions.
Session mode/reset/warmup/input-touch/output initialization and schedule identity
must match the freeze. A reset-contract session requires nonempty retained reset
evidence matching the frozen identity; a fresh owned session declares no reset
file. This single-measurement gate cannot establish uniqueness of sessions,
independence, balanced full coverage, IID behavior or absence of drift across a
request; the request-level gate and external reviewer retain those obligations.

UTC windows use the explicit `Z` suffix, strictly increase and cannot be future
windows. Baseline A/A pilot windows follow baseline selection and finish before
policy freeze; training follows preregistration and finishes before baseline
selection; selection, held-out and synthetic correctness receipts follow
candidate and policy freeze. The full experiment-level pilot/selection/held-out
chronology is an additional request-level requirement.

## Independently selected synthetic fixture oracle

`SyntheticFixtureOracle(expected_manifest, sidecar, version,
expected_manifest_sha256, sidecar_sha256)` is an explicit caller-supplied trust
anchor. Select these expected values and pins independently of the measurement
receipt. An export envelope must bind this independently supplied fixture oracle;
it must not manufacture a trusted anchor from the measurement's claimed expected
hash. A path or matching version label alone is insufficient. Both pins are
rechecked. Consistently replacing expected bytes and their sidecar at the same
paths cannot alter an existing anchor.

`write_fixture_oracle` binds supplied expected values; it does not compute or
validate an Axiom oracle. Its sidecar has exactly `schema`
(`axiom-synthetic-fixture-oracle-v1`), `provenance` (`synthetic`), `oracle_version`,
`expected_manifest`, `expected_manifest_sha256`, `invocation_sha256`, `status`,
`first_bad_index`, `events` and `stdout`. The expected manifest and these two
semantic-file references are relative to the expected state's directory. The
sidecar is included in that state's verified closure. All metadata must bind the
exact expected invocation/status and complete manifest. Empty semantic files in
the independently authored expected fixture explicitly declare that this
fixture's admitted operation emits no such observables. Diagnostics remain
separate even when semantic files are empty.

Expected values and provenance remain the fixture author's responsibility. Tests
use the independently hand-worked input `[0,1,2,3]`, initial output `[0]`, and
output `[1+4+9+16] = [30]`; two observed candidates that both return `[99]` agree
with each other but fail this independent expected-state comparison. This tiny
literal fixture is no evidence of a reviewed scalable Axiom oracle.

## Closure and trust boundary

State, acquisition and oracle manifests and every referenced chunk are traversed.
The combined closure also retains identities, raw observations, reset evidence,
semantic files and diagnostic files. Enforce at most 16 MiB per file, 256 MiB
summed over unique resolved paths, and 16,384 files; equal bytes in different
files count twice. Expanded logical bytes from actual plus expected state have
an additional explicit bound. Recheck retained file identities before returning.
Defaults match the pinned evaluator; an adapter must enforce its own complete
request closure as well. An immutable admission record is a snapshot, not a
permanent guarantee about mutable paths; revalidate before export/evaluation.

Every admission record retains assumptions about collector execution and
completeness, hardware/OS controls, raw observation honesty, disclosed history,
sampling/reset independence and fixture-author oracle correctness. JSON/scalar
consistency cannot establish these assumptions. There is no threshold retuning,
pooled-family inference or automatic adoption in this API.
