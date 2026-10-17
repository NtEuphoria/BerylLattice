# Independent evidence and experiment plan review

Date: 2026-10-16. Final status: PASS after targeted re-review. No unresolved important finding remains in the inspected planning scope. This is a planning review, not an implementation or experiment result.

## Inspected scope

Read the shared `design.md`, package `README.md`, plans 03–05 in full, and relevant native build/invocation sections of plan 01. Cross-checked the current `experiment-v1.md` and `export-v1.md` protocols and the pinned Core evaluator's cost/resource, freeze, selection and inference code. Inspection was read-only except for this review artifact. No product implementation, builds, native executions or benchmarks were performed. The author was concurrently refining these documents; findings identify named sections and quoted contracts rather than relying solely on shifting line numbers.

The design correctly separates exact source, family and specialization identity; source-AST interpretation from physical scheduling; actual acquisition from expected state; complete byte comparison from CAS identity; v1 from new native admission; the old exposed corpus from prospective holdouts; and engineering progress from publication claims. The two-store architecture and campaign-wide accounting address the previously identified closure-size and repeated-capture hazards. The initial contract findings below are retained for review history; their final dispositions follow.

## Final dispositions and additional chronology check

| Finding | Disposition | Written resolution inspected |
| --- | --- | --- |
| E1: incomplete whole-call accounting | Resolved | M1 now requires a complete contiguous phase partition, actual attribution of instrumented boundary overhead, and exact equality between the paid sum and enclosing call span; uncovered residual cannot be subtracted or invented away. Qualification and admission remain unavailable if this cannot be established. |
| E2: unequal sample/batch counts | Resolved | O5 and M1 use `N = 2*n_pilot*b_pilot + 2*n_final*b_final`, sum mixed shapes independently and retain prior pilot work when a final-stage reservation changes. The explicit 32/64 example yields 192 calls. Training/qualification/failure work remains additional. |
| E3: training/admission dependency | Resolved | M5a freezes policy and artifact-metric jobs; M3 collects; M6a produces independently admitted training records and the complete `VerifiedTrainingSet`; M5b chooses the baseline; M6b admits pilot/final roles separately. Immutable `ExperimentHistoryV2` prefixes contain actual events only. `freeze_selected_artifact` consumes the actual `policy_frozen` history prefix, so it requires neither fabricated future measurement events nor a completed final experiment. Wrong-stage/future-event controls are specified. |
| E4: build/edit metric ambiguity | Resolved | M5a defines two versioned five-job profiles, exact measured stages/cache assumptions, deterministic edited shape/byte patch, third-order statistic with ordinal ties, exact median-job runtime executable, and per-artifact receipt binding. Unsupported edits remain unavailable. Other compile/edit jobs stay diagnostics, and repeated shared metrics do not become independent samples. |
| E5: constrained fixed-baseline eligibility | Resolved | Exact baseline groups and the all-required-cell common eligible portfolio are defined. M5a freezes the legality matrix before the runtime schedule, excludes ineligible plans globally while retaining their legality evidence, and collects every unchanged required cell for each eligible fixed plan. M5b uses equal cell weighting and M/I/R ties; no common portfolio or final-shape ineligibility has an explicit unavailable outcome. |
| G3/G4 research-table wording | Resolved | R8 now names the qualified oracle/complete acquisition at scalable correctness, and explicitly reserves performance-collector qualification for G4. |

The author identified an additional current-clock freeze ordering problem during amendment, which this re-review independently checked against the actual pinned evaluator. Its CLI takes `freeze --input ... --output ...` and calls `time.time_ns()` internally; evaluation requires the retained freeze to precede final selection, and final samples to follow selection. An evaluator freeze created after the final measurements cannot establish that chronology.

The written plan now resolves this additional issue: `NativePilotAdmission` consumes baseline-only A/A evidence and the actual baseline/candidate history without requiring a future freeze; `freeze_native_pilot` runs before final selection and retains the actual sealed evaluator bytes/time, policy event and pilot evidence closure; final export reuses that seal without refreezing. M8 and the operational dependency sequence place pilot admission, actual policy freeze, final selection, final collection, final request admission and evaluation in that order. Tests explicitly reject post-measurement/backdated freezes and require reuse of the original seal. Final `FrozenExperimentV2` is assembled from completed actual history for final admission/reporting.

The re-review also checked these cross-plan details:

- The proposed correspondence matrix is exactly `2*13*3 + 4*2*3 = 102` ordinary calls and `5*3 + 1 = 16` deliberate faults, totaling 118 planned calls. The nine valid patterns count correctly, large cases include valid/rejection paths, and faulty first-invalid and final-chunk controls have appropriate inputs. These are proposed counts, not executed observations.
- A fixed plan policy is distinct from its per-specialization binaries. Final receipts bind exact specialized executables; an inventory/family digest does not replace their identities.
- Complete per-invocation acquisition/comparison survives CAS sharing. Separate semantic/qualification stores retain full traversal obligations; the campaign index adds 256-root and 131,072-file caps, 8 GiB semantic retention, bounded quarantine/temporary capture and cumulative logical-work accounting. Splitting roots does not expand those budgets.
- The historical exposed corpus remains descriptive. Prospective custodial data preparation has explicit access restrictions and logging; unavailable separation cannot be presented as fresh holdout evidence.
- The full research/publication scope remains conditional on actual evidence and closest-prior-art comparison. A planning PASS supplies no theorem, native execution, instrumentation qualification or publication approval.

## Initial findings retained for history

### E1 — High: the analytical total may omit time inside the promised checked-call boundary

**Location:** plan 04, M1 phase accounting; M7 evaluator mapping; shared design checked-call scope.

M1 defines the analytical total as the sum of measured disjoint paid components, but only requires each component to lie inside the full span, and separately retains a timer residual. The pinned evaluator uses that sum as its primary measurement. A collector can therefore omit gaps between phase intervals, including dispatch or instrumentation boundary work, while the report calls the result a complete checked call. The `test_paid_intervals_are_disjoint_and_complete` name does not supply the missing numerical invariant.

**Minimal fix:** require an ordered contiguous partition of the exact outer checked-call interval. Consecutive intervals share the same sampled boundary; the first starts at call start and the last ends at call end. Bind each interval to a predefined paid category, including deterministic attribution of instrumented boundary overhead; do not subtract a measured overhead estimate or put unexplained residual into a fabricated component. Require `sum(paid_ns) == call_end - call_start` and reject gaps, overlaps and omitted cleanup. If the host cannot provide this contract, leave that measurement scope unavailable or explicitly define a different metric without a whole-call claim. Add injected inter-phase delay and one-nanosecond gap controls to M1/M2/M6.

### E2 — Medium: reservation arithmetic assumes equal pilot and final pair counts

**Location:** plan 03 O5; plan 04 M1/M8.

O5/M1 use `N=4n`, while M8 permits choosing the final count after baseline-only pilot results. Once a 32-pair pilot leads to a 64-pair final experiment, the actual unbatched count is 192, not an unqualified `4n`. Using the same field for both counts makes the frozen schedule and exact work reservations ambiguous. A batch-policy change after pilot similarly cannot retroactively change pilot acquisition counts.

**Minimal fix:** name and freeze `pilot_pairs`, `final_pairs`, `pilot_batch_size` and `final_batch_size` separately. Compute `N = 2*pilot_pairs*pilot_batch_size + 2*final_pairs*final_batch_size`, plus explicitly scheduled warmups/control/preparation invocations where relevant to campaign work. Preserve `4n` only as the equal-count/batch-one example. Test 32/64 unequal counts and independently changed batch sizes. Recheck reservations after an allowed baseline-only amendment and before executing any newly scheduled invocation; never erase the already paid pilot work.

### E3 — High: verified training selection and native admission have a bootstrap dependency

**Location:** plan 04 M5 `VerifiedTrainingSet` and M6 dependencies/interfaces; README G4→training order.

M5 chooses the fixed baseline from a `VerifiedTrainingSet`, but the plan does not assign a producer or admission contract to that type. M6 owns native measurement eligibility and depends on M5, including selected baseline/experiment chronology. The master graph places native admission before training. Implementers can resolve this inconsistency by either trusting unadmitted `CollectedRun` fields for baseline choice or by waiting on a baseline that requires the very admission being constructed.

**Minimal fix:** split native admission into run/training evidence admission and complete experimental-request admission. Run/training admission depends on M1/M2, source-oracle/acquisition evidence, exact training schedule and resource/build bindings; it does not require a chosen fixed baseline or A/A pilot. Assign the producer of `VerifiedTrainingSet`, with exact completeness/eligibility rules, to that earlier boundary. M5 consumes it. Complete A/A/A/B chronology/request admission then depends on M5. Update task dependencies and the master graph consistently. Test that forged or incomplete training never selects a baseline, and that a complete qualified training set can be admitted before a baseline exists.

### E4 — Medium: mandatory build/edit resource fields do not identify one measured job

**Location:** plan 04 M5 compilation accounting and M7's six required resources.

The evaluator applies a maximum 2× `build_ns` ratio and 10% `edit_check_ns` growth rule. M5 lists cold build, warm replay, no-op build, body/shape/constraint edit and process-restart jobs but does not select the precise job/statistic that supplies either mandatory scalar. Two implementations can therefore compare different cache states, edits or aggregations while producing schema-valid resources. Static text identity is comparatively well specified.

**Minimal fix:** define versioned mandatory build and edit/check job contracts, including exact input/edit, clean/warm state, included stages, repetition count/ordering and deterministic retained statistic or selected-run binding. Keep other job results diagnostics. Bind every measurement's `build_ns` and `edit_check_ns` to the exact corresponding `CompilationReceipt` and candidate/base artifact identities; a missing or differently scoped job makes the resource gate unavailable. Test a swapped edit kind, warm-for-cold substitution, altered statistic and reuse from another artifact.

### E5 — Medium: cap-constrained best-fixed baseline needs a complete eligibility rule

**Location:** plan 04 M5 baseline policy.

The `test_cap_constrained_baseline_uses_same_cap` name does not define whether the best fixed schedule is selected once globally or once for each compatible constraint regime, or what happens when a schedule violates the cap on one training/measurement shape. Dropping infeasible cells or comparing an unconstrained baseline against a constrained selector can favor either variant without representing the declared deployment policy.

**Minimal fix:** freeze baseline groups by the exact operation/cache/target/resource-constraint policy. Specify the eligible fixed schedules as those admitted on every required cell of that group, sum the equally weighted retained medians only over the unchanged complete cell set, and retain M/I/R tie order. No common eligible fixed schedule yields an explicit unavailable baseline unless a separately preregistered deployment fallback policy is compared and labeled as adaptive. Apply the same constraints to final baseline and candidate, and test a cap that excludes materialize on only one required shape.

## Smaller clarification

Plan 05 R8's scalable-execution row includes “oracle/collector qualification,” while the common G3 gate correctly does not require the performance collector. Name acquisition correctness/qualification separately from M2 physical timer/resource qualification so completion of the engineering milestone cannot accidentally acquire a G4 dependency.

## Verification boundary

The targeted re-review covered the named interfaces, staged task dependencies, actual evaluator freeze/selection ordering, exact phase partition, unequal-count/batch formulas, resource metric bindings, constraint-group baseline rules, campaign quotas, proposed correspondence count and G3/G4 wording. No implementation tests were run for this documentation-only review. The later implementation must execute the planned behavioral and physical controls before any success claim.
