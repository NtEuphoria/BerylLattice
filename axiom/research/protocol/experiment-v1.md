# Axiom frozen experiment v1

This declaration format implements the 2026-10-15 performance protocol's frozen
workloads and chronology. It supplies no native measurement, scalable semantic
oracle, proof of independence, or performance result. It cannot discover
unreported accesses or independently attest the declared UTC times. Retain all
known accesses, including accesses that make the run ineligible.

## Identity and exact data

`experiment_manifest.py` provides immutable `Workload`, `AccessRecord`,
`SamplingPlan`, `ExperimentSpec`, `Receipt` (also `ChronologyReceipt`),
`FrozenManifest`, and `ChronologyResult` records. Collections inside typed records
are tuples. Hashes are lowercase SHA-256; UTC timestamps have a `Z` suffix and up
to six fractional digits. Integer fields reject booleans.

`Workload.content_sha256` hashes canonical JSON containing logical semantics,
output shape `{W,H}`, and the complete original input hash. It excludes dataset
role, paths, generator labels, seed, cap, entry contract, output initialization,
and cache regime. `Workload.stratum_sha256` additionally binds generator/version,
seed, cap (`null` means unconstrained), entry contract, initial output hash, and
cache regime. Roles are correctness, training, pilot, selection, and held_out;
changing a role or stratum label cannot remove content contamination.

Training `(W,H)` values are `(32,32)`, `(128,128)`, `(512,512)`, `(2048,2048)`,
`(4096,64)`, `(64,4096)`, each with seeds 1, 2, 3, 4. Held-out shapes are
`(31,33)`, `(127,129)`, `(511,513)`, `(2047,2049)`, `(4093,67)`, `(67,4093)`,
`(8191,1)`, `(1,8191)`, each with seeds 65537, 65538, 65539, 65540. Every cell must
be declared. Extra cap/cache/operation strata may use these exact cells; duplicate
role/stratum entries and extra timing shape/seed cells are rejected. Correctness
patterns remain separate.

The timing data algorithm is fixed regardless of display labels. Start with u64
state equal to seed; update `state = state*6364136223846793005 +
1442695040888963407 (mod 2^64)` for each of `(W+1)*(H+1)` row-major input elements
and emit `(state >> 32) & 1023`. `approved_input_sha256(W,H,seed)` hashes the actual
little-endian i32 stream in bounded chunks. Freeze/load checks input hashes for
every timing workload and known non-correctness access against this stream.
Renaming a generator does not change the algorithm. Correctness-pattern hashes
must truthfully describe actual inputs; this format does not acquire their bytes.
Generated input is expected data, never observed post-call input or native
acquisition evidence. The bounded Core admission profile stays separate from
these larger generated dataset identities.

One primary stratum is exactly `(W,H,seed)=(2047,2049,65537)`, unconstrained cap,
`ordinary_checked_call`. Optional `primary_stratum_sha256` disambiguates multiple
cache strata. Other results are descriptive. All declared workloads share the
primary's logical semantics.

## Known accesses and freezes

`holdout_rule` must be `input` or `shape`. Input holdout rejects a known tuning
access with held-out content identity. Shape holdout additionally rejects every
known tuning access to held-out dimensions, even with different data, generator
names, contracts, caps, or cache regimes. Access purposes include training,
selection, tuning, correctness, and baseline A/A pilot. All non-pilot accesses
count for contamination; relabeling tuning as correctness cannot permit use.

`training_history_complete` must explicitly be true and all training content must
have a declared training access. This asserts reported knowledge, not discovery.
Non-pilot tuning accesses must follow dataset preregistration and precede or
coincide with candidate freeze. Training must finish by fixed-baseline selection.
Earlier accesses must be retained and cause rejection, rather than erased.

Required ordering is dataset preregistration <= selector-design freeze <= fixed
baseline selection <= candidate freeze < pilot-policy freeze. Objective,
selector design/coefficients/ties/filter/budgets/fallback, compiler configuration,
and baseline/candidate artifacts are committed through their identity fields.
The baseline policy remains the approved sum of equally weighted per-training-
cell median checked-call times, ties M, I, R. These declarations do not compute
training costs or prove correct baseline selection.

A pilot exposure must declare `baseline_aa=true`, follow selector-design and
fixed-baseline selection, and precede pilot-policy freeze. It is an allowed
calibration role; candidate feedback cannot be relabeled baseline A/A. Selector
design freezes before any pilot exposure. All identity fields stay pinned
through pilot, final selection, and measurement.

`Receipt` binds one stratum, one UTC window, all five frozen identities, a role,
and the baseline-A/A flag. `validate_chronology(manifest,receipts)` revalidates the
manifest and every supplied record. Each final measurement needs its own
stratum's A/A pilot finishing before policy freeze and exactly one selection
receipt starting after both candidate and policy freezes, finishing strictly
before measurement. Independent shape/seed/cache/operation strata cannot share a
pooled receipt, pilot or selection. Training receipts must use declared training
strata. Every disclosed receipt must follow dataset preregistration. Non-pilot
accesses starting by candidate freeze obey the same content/shape holdout rule as
known-access records, including receipts labeled correctness. Correctness work
starting in that tuning window must also finish by candidate freeze. A held-out
correctness acquisition after candidate freeze is allowed as final verification
only after policy freeze and a completed selection for that exact stratum;
relabeled generator/cache strata need their own selection. Legitimate baseline
A/A pilots keep their explicit calibration exception. Chronology is one admission
prerequisite; complete state, instrumentation,
resources and receipt authenticity are separate gates.

The evaluator threshold is the fixed literal
`max(5%,pilot_p95_absolute_paired_variation)`. There is no numeric threshold knob,
changed-objective loophole, pooled interval, or multiplicity claim.

## Sampling

`SamplingPlan` fixes an even count from 30 through 1024 before candidate
measurement; the protocol's normal starting declaration is 32. Count and order
cannot change mid-run or stop when an interval first looks favorable. Each
shape/seed workload repeatedly uses the same complete input; distinct seeds
remain separate strata rather than interchangeable IID samples.

The versioned `sha256-sort-balanced-abba-v1` schedule starts with count/2 indexed
AB labels and count/2 indexed BA labels. Sort indices by binary SHA-256 of ASCII
`version:randomization_seed:index`, ascending, and emit the indexed labels. Exact
orders are persisted and checked alongside seed, count, warmup, input-touch, and
output-initialization declarations. `SamplingPlan.sha256` binds plan and orders.

Fresh samples require disjoint owned process sessions containing the checked
operation. Repetitions within a session are one sample. A PID cannot establish
independence; record and assess the independence assumption and reset protocol.
Reusing sessions requires an externally established reset contract with a
mandatory evidence hash. The manifest records these claims; collector/admission
must bind actual sessions and retained drift/run-order diagnostics. Restart does
not flush LLC or OS page cache. Validation warms input; the timer must include
required preflight and scratch cleanup.

## Serialization and loading

`freeze_manifest(spec,directory)` writes canonical ASCII JSON in
`experiment-<sha256>.json` using exclusive creation and descriptor-pinned
directory traversal. The returned declaration must still match the requested
bytes and typed spec after writing. Existing identical bytes may
be reused; differing content fails. `load_manifest(path)` uses state-artifacts
v1's bounded strict canonical-JSON reader, rejects missing or unknown fields at
every record level, and recomputes primary, threshold, schedule, approved data
hashes and history constraints. `FrozenManifest.sha256` hashes the whole canonical
envelope. `revalidate()` rereads and compares the loaded declaration, detecting
changed bytes or typed records. `Workload.to_record/from_record`,
`ExperimentSpec.to_record/from_record`, and `Receipt.to_record/from_record`
provide strict record shapes downstream. A typed declaration/input identity has
no `native_observed` claim and cannot convert synthetic into native evidence.
