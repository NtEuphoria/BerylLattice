# Independent source oracle: O2 acceptance

The source-AST oracle is implemented and independently approved at
`eeb8f2c8e247d42abc73c6727ddfed57ab99a1d9`, against base
`eabd3098d85427bdad906b79a98aea723d3235df`. It evaluates the original admitted
source and streams a complete state without retaining producer/output tensors.
This is O2 acceptance, not O3 qualification, a native result or a speed claim.

The [continuation plan](../superpowers/plans/2026-10-16-axiom-proof-oracle-continuation.md)
and [protocol](../../axiom/research/protocol/source-oracle-v1.md) define the
contract. Source/group association, declaration names and bounds are interpreted
directly. All input values are preflighted before equations. Invalid input
preserves every input and original-output value and reports the earliest bad
index. Work/resource/cancellation failures cannot publish a completed result.

The implementation copies verified input to an owned anonymous snapshot and
uses a bounded two-chunk reader. It reserves conservative storage/file/metadata
quotas before writing. A complete state is published only after state verification,
final invocation revalidation and the final cooperative control check.

## Immutable review subject

| Artifact | SHA-256 |
| --- | --- |
| `axiom/research/source_oracle.py` | `a29677691160c2f9b19fa580f47429760ca647d9ff0d7340d66ea07a35dbcb8f` |
| `axiom/research/tests/test_source_oracle.py` | `8544cec5d9c7e7c10320150b1672cb7e0f62a2e341684d5986abb9387e37a49d` |
| `axiom/research/protocol/source-oracle-v1.md` at the reviewed commit | `e68b8137a01c227f05951eaff8f9071b2f15e5cdbdd5c11dbf132b195e0b3b05` |

Fresh reviewer `/root/review_source_oracle` returned **SPEC APPROVED** and
**QUALITY APPROVED**, with no blocking findings. The reviewer used an isolated
Git archive of the exact commit and independently inspected the source,
dependencies, quotas, failure phases, descriptors and publication ordering.
The complete report is retained at
`.superpowers/sdd/axiom-checked-execution/o2-review.md`.

## Executed verification

| Check | Actual result |
| --- | --- |
| O2 suite from `axiom/`, normal and optimized Python | 29 tests passed in each mode |
| O2 suite from `axiom/research/`, normal and optimized Python | 29 tests passed in each mode |
| Reference/source-profile/blob/invocation/state regressions, normal and optimized Python | 51 tests passed in each mode |
| Reviewer-authored exact quota, publication and descriptor fault probes, normal and optimized Python | 29 checks passed in each mode |

These selected suites had no skipped tests. Both the implementer and independent
reviewer executed the focused/dependency suites. Retained tests cover original
node/group behavior, independent small-reference equality, every invalid-input
position/extreme, nonzero canaries, generic seven-byte transport chunks,
sixteen-byte state chunks, minimum/evicting caches, exact fuel, typed forgeries,
file mutation, cancellation, allocation/I/O failures and pre-write quotas.
The independent probe is retained as `o2-independent-probe.py` with SHA-256
`6b3a6d0510bc7e5b5da4dcc460edcf2fb88e77a9ee6a2b51c1bb8572cf3c4b1e`
in that evidence directory.

The first intentional RED assertions and subsequent corrections remain in the
implementation logs. An ancestor-open descriptor leak found during controller
inspection was fixed before the reviewed commit and has a permanent regression
test. The final independent review requested no fixes.

## Disclosed large correctness control

After review, the controller executed the same immutable code on a disclosed
2048×2048 all-maximum input control: input 1023, initial-output canary 17,
expected output 4,194,304 at every output coordinate. This is a known-value
correctness control, not a fresh holdout or native benchmark.

| Observation | Actual result |
| --- | --- |
| Full input values checked/preserved | 4,198,401 |
| Full output values checked | 4,194,304 |
| Complete semantic state | 33,570,820 bytes |
| Original AST node visits | 322,961,428 |
| Logical source input reads | 33,554,432 |
| Input acquired / snapshot written | 16,793,604 / 16,793,604 bytes |
| Snapshot bytes read | 33,587,208 |
| Input cache fills / peak retained payload | 17 / 2,097,152 bytes |
| Oracle function elapsed time | 210.351657 seconds |
| Process outcome | Exit 0; no timeout; all identity/count/value checks passed |

The controller selected a 420-second cooperative deadline and a 480-second
process supervision limit after complete 32/128 controls established execution
feasibility. The elapsed time includes the oracle's validation, preflight,
computation, writing and publication. Invocation creation and the postreturn
full-value scan are outside that interval. It is recorded to budget correctness
testing, not to characterize Axiom-generated execution performance.

Exact evidence:
`/workspace/scratch/axiom-o2-large-bah862um/evidence/control.json`, with SHA-256
`9303d089de66d409e54cff235473392c8680cbe896778f892fbbf78333b2046d`;
`/workspace/scratch/axiom-o2-large-bah862um/supervision.json` and `run.log`.
The source snapshot is pinned to the reviewed commit. The controller script,
its hash and a copy of the result are retained in the execution evidence directory.

## Limits and remaining gates

The original parser/profile and state primitives remain shared trusted code.
Only the admitted fixed-buffer family is supported. Deadlines are cooperative;
existing helper/OS calls have opaque uninterruptible intervals. Cache limits
cover retained input payload, and temporary limits cover logical payload;
neither is a Python RSS or physical disk reservation. Local counters omit
opaque helper traversals and do not satisfy campaign-wide I/O accounting.
Stable files and the absence of hostile same-UID races remain explicit
assumptions. Filesystem cleanup refusal may leave private staging, without
granting a completed-state result.

The production proof checker remains separately gated by C1. O3 must establish
reviewed code/runtime selection and independently executed expected-state
authority before this oracle can anchor native correctness. Native ownership,
full per-invocation acquisition/comparison, measurement qualification and
publication remain distinct later requirements.
