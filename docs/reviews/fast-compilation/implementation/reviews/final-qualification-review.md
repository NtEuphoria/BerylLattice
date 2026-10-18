# Final qualification evidence review

**Evidence verdict: PASS for arithmetic, artifact binding and reported audit consistency. Performance verdict: mixed; the target misses below remain failures.** No material measurement defect was found. This review does not certify that every original performance goal passed.

Reviewed the completed JSON evidence under `/workspace/scratch/beryl-fast-compilation/qualification-final`, its `run.json`, actual selected archives, artifact manifests/provenance and preserved initial kernel reports. Read-only scripts recomputed aggregates and checked raw records; no test suites, builds, executable runs, browser runs or new benchmark samples were performed. No external writes occurred. Only this uncommitted review report was added.

## Identity and sample integrity

- Final source revision is `775930bc88530b5babb41c71274c492bd550d2cd`. All 36 candidate module hashes in every native round match that exact Git revision, and all rounds report a clean tree. All 26 baseline snapshot module hashes match declared origin `39dc2f6df136c643cfd030ce4470503e807750fe`; observed Git identity correctly remains null for the snapshot.
- Actual final public ZIP SHA-256 is `bdea7e03ec93d3df176ba39a9670ffc6f45f754df7f83dcb68ba2ef788b243c6`. It matches the browser sites, kernel-artifact manifest/provenance, paired-process provenance and public-process report. Baseline ZIP is `cb7304afabbfee94c4184f1c34574732f0f241c2a674222d6c3a8ee014bb6634`. Actual ZIP bytes and recorded module/member hashes match. Kernel source and plan files match their hashes and upstream provenance; recorded imports belong to the selected ZIP.
- Run-step names are unique, logged steps are serial and every retained log matches its recorded hash. The final evidence retains the paired-process exit 2 and prepared-browser exit 1. `run.json` says complete, not that all targets passed.
- Raw medians, nearest-rank p95s and reported ratios were independently recomputed. All checked aggregates agree. Native, kernel, cold-browser, prepared and process paired orders match their alternating policies. The two prepared/process helpers retain one identified warmup pair and all 21 measured pairs per case. No selected raw sample was removed or replaced in the inspected final records. This is a statement about retained evidence, not an inference about unrecorded activity.
- Cold-browser evidence contains 84 distinct temporary-profile arguments for 84 preparations, all marked fresh process/profile. Each pair uses identical source bytes, and each prepared artifact executes two distinct inputs. This supports the documented runtime-ready engine-cold scope; it does not make runtime boot or full UI startup part of source preparation.

## Independently reproduced target table

Native figures below are full source-through-link medians, not compiler-only costs. Direct C and Rust build medians are **88.673804 ms** and **151.915742 ms**, respectively.

| Measurement | Baseline → final | Relevant result |
| --- | --- | --- |
| Native 15x15 cap64 | 604.908269 → 187.759514 ms | ≤250 ms PASS; stretch ≤200 ms PASS; 2.117418× direct C: ≤2× C FAIL; 1.235945× Rust PASS |
| Native 15x15 cap128 | 521.218570 → 184.346553 ms | ≤250 ms PASS; stretch ≤200 ms PASS; 2.078929× direct C: ≤2× C FAIL; 1.213479× Rust PASS |
| Cold browser 15x15 cap64 | 617.6 → 150.7 ms | About 4.098× faster PASS; ≤150 ms FAIL by 0.7 ms; stretch ≤100 ms FAIL |
| Cold browser 15x15 cap128 | 602.2 → 146.6 ms | About 4.108× faster PASS; ≤150 ms PASS; stretch ≤100 ms FAIL |
| Prepared browser 1x1 ramp | 2.9 → 3.3 ms | Ratio 1.137931: ≤1.10 FAIL; remaining five prepared cases PASS |
| Whole process 1x1 checkerboard | 0.721931 → 0.799559 ms | Ratio 1.107528: ≤1.10 FAIL; remaining five process cases PASS |

All four native callable-kernel cases have 21 pairs of one million measured calls per program/sample and pass the ≤1.10 ratio-of-medians target:

| Kernel case | Candidate/baseline median |
| --- | --- |
| 1x1 cap0 | 0.888415241 |
| 5x7 cap0 | 0.590913275 |
| 15x15 cap0 | 0.956968972 |
| 15x15 cap128 | 0.973597520 |

These ratios apply to the disclosed mutation/capture-plus-kernel loop. Prepared request latency includes fresh verification; whole-process latency includes startup and pipes. Passing one scope cannot erase a miss in another.

Do not round 150.7 ms down into the 150 ms budget or characterize either small-case regression as noise. Shared-host load and timing variance are disclosed limitations, not evidence that an observed miss should pass. Tail behavior is mixed: prepared 15x15 ramp p95, for example, has a candidate/baseline ratio about 1.2848. A claim that all tails improved would be false.

## Audit and instrumentation evidence

- Native: 168 sampled source-to-executable preparations retain successful independent execution-audit status, matching source identities, expected pipeline selection and full intervals at least as large as source plus compiler/link intervals. Separate candidate diagnostic traces show one admission, three generations/validations, one semantic check, one encoding, one correspondence and one emission; wall-time samples do not include those diagnostic runs.
- Direct builds: 21 raw builds per language, correct alternating order, matching median/p95 and 42 executable hashes are retained. Both input-family audits per executable are recorded as successful. The helper does not retain raw audited outputs, so this review relies on the already-reviewed audit implementation and completion flag for those executions; it does not claim to have re-executed them.
- Kernel: 168 sampled process records retain successful driver audits, one separately identified first-call warmup, correct elapsed-ns/call calculations and paired seed/checksum/final-output equality. Their contract remains rotating timed capture plus complete final timed state and full untimed replay. It is not a claim that every intermediate timed output was captured.
- Cold browser: all 168 complete observations were independently recomputed from the retained changing inputs and direct formula; input preservation and zero status agree, and the retained original-AST audit flags are successful.
- Prepared browser: all 264 retained request observations, including 12 warmup observations, match retained inputs and independently recomputed formula outputs, successful original comparison and exact prepared reuse. The failure is solely the declared median guard.
- Paired process: all 264 retained raw stdout observations, including 12 warmup observations, decode to the independently recomputed formula; all return codes and audit flags pass. The failure is solely the declared median guard.
- Public Beryl/C/Rust process comparison: six cases each retain 21 measured values per language and one warmup request; recomputed medians agree and all cases record passed correctness. This supplemental comparison is not substituted for either failing old/new request/process guard.

## Preserve initial misses and separate the release decision

The earlier `kernel-5x7-cap0-final.json` ratio **1.229434856635754** and `kernel-15x15-cap128-final.json` ratio **1.1013023869593654** remain failed results. Their baseline C hashes equal the final baselines, while their candidate C hashes differ from the final candidate artifacts. The final run follows the committed native change `b5f7d2e` and a new full qualification under `775930b`; it is evidence for changed code, not permission to discard the earlier misses. Retain both generations and the documented reason for the native change. Likewise, the earlier prepared pass must not replace the final prepared failure.

The approved specification's performance contract explicitly says a miss is a measured outcome: keep faster validated stages, report the miss and choose the next experiment from the residual. That supports describing this as a **correctness-validated bounded prototype with measured performance improvements and documented target misses**, subject to the controller's existing release authorization and completed correctness/public-export reviews. It does not support “all performance gates passed,” universal execution parity, or complete success against every original acceptance target.

Publishing that accurately labeled prototype is a release/process decision, separate from this measurement-validity verdict. This review neither converts any miss to a pass nor creates an additional authorization requirement. Keep rollback `149e4d6`, the bounded 256-input scope and F1 BLOCKED status explicit; this benchmark evidence does not qualify scalable F1 or justify weakening correctness, quotas or constraints.
