# Supplemental measurement review

Read-only static review of `/workspace/scratch/beryl-fast-compilation/measure-prepared-browser.cjs`, `measure-paired-process.py`, and `measure_direct_builds.py`, plus completed prepared-browser/direct-build/kernel reports and artifact provenance. No tests, compilation, browser launch, timing experiment or agents were run. Active cold-browser reports were neither read nor changed. This report is uncommitted.

## Nonblocking evidence-retention limitation

**Direct-build failures would discard the measurement evidence.** In `measure_direct_builds.py:43–61`, compilation uses `check=True`, executable audits may raise, and the output report is created only after all samples and audits finish. There is no exception/finally persistence. A build error, malformed executable output or formula mismatch would therefore lose the prior raw timings, omit the failing output from a report, and remove temporary binaries on unwind. Unlike the paired helpers, this helper did not promise incremental failure capture, and the controller confirms no failed attempt occurred. This is a nonblocking limitation of future failed runs, not a numerical or audit-validity finding against the completed 21-success report. Preserve the exact used script/hash and report; no post-run helper edit or repeat measurement is required for this review.

## Prepared-browser helper

**Timing/qualification contract: PASS.** The timer surrounds the actual public `transport.runDemo` request after explicit preparation, including transport, validation, execution, observation and retained original-AST verification. The separate external formula and pair audits, report serialization/fsync and explicit preparation are outside that timer. This is prepared verified-request latency, not isolated Wasm/kernel execution. A reused process/context/Worker and potentially warm engine/HTTP caches are clearly disclosed; there is no cold claim.

Both versions receive the same changing bounded inputs. Exactly one identified warmup pair per case is retained and excluded; all 21 measured pairs remain, with alternating order. Preparation identity, backend/schema, exact selected plan, source, input/output, initial compilation cost and reuse are checked. Local/served release manifests and file hashes are compared, every compiler ZIP member is checked, and actual public Workers are counted to detect resets. This is sufficient binding to the supplied immutable site artifacts under the controller's stable-site assumption.

The helper saves observations before external audits can reject them, retains partial failures, and enforces the stated 1.10 ratio-of-medians guard across all six cases. Median and nearest-rank p95 calculations are correct for the required 21 samples. The completed report passes all six median guards. Tail measurements are retained, not gated: for example, 15x15 ramp p95 rises from 20.5 ms to 28.1 ms (ratio about 1.371). A median-guard pass must not be described as all percentile timings improving.

## Whole-process helper

**Timing/qualification contract: PASS by static inspection.** Builds finish before any samples. Each timer measures one fresh subprocess, including process/pipe/wait overhead; input construction, JSON parsing, formula evaluation and paired full-output checks remain outside timing. The scope explicitly acknowledges warm OS caches and process overhead, so this cannot substitute for callable-kernel throughput.

The artifact loader binds exact source, selected plan and C bytes to the reviewed provenance/manifest, then compiles snapshotted C bytes and records exact compiler, command and executable identities. It retains the upstream ZIP identities/import-origin evidence rather than regenerating artifacts. Both sides receive byte-identical changing stdin; uniqueness is checked. One seed-0 warmup pair is retained separately, 21 measured pairs alternate order, and no retries or measured-sample removal occur. Raw output is stored before audit; handled exceptions and timeouts persist partial evidence. Median/p95 and pair-ratio calculations are correct, and any median threshold miss produces exit 2 without deleting the completed data. No execution verdict is claimed in this review.

## Direct C/Rust build helper

**Successful-run timing/data contract: PASS, with the nonblocking failure-retention limitation above.** Each measured interval surrounds a real fresh compiler/link subprocess on the unchanged direct source, with a unique executable path. Source/compiler hashes, flags and all 21 raw build costs and executable hashes are recorded. C/Rust order alternates. Both changing ramp and checkerboard executions and independent formula checks run afterward. No runtime correctness audit is included in build latency. Median and nearest-rank p95 are correct.

There is no separately discarded build warmup; all 21 builds are measured. The helper describes ambient infrastructure as warm and makes no cold-cache guarantee. It is a direct-language build-cost reference, not a baseline/candidate kernel regression guard. The completed report records C median/p95 92.659138/118.566184 ms and Rust 149.031016/163.49775 ms, with every build audited. No benchmark shortcut or suppression of a completed unfavorable sample was found.

## Existing kernel failures remain release-gate failures

The separately reviewed callable-kernel reports contain 21 samples each and retain these ratio-of-medians misses against 1.10:

- `kernel-5x7-cap0-final.json`: **1.229434856635754 — FAIL** (about 22.94% slower).
- `kernel-15x15-cap128-final.json`: **1.1013023869593654 — FAIL** (about 10.13% slower).

Neither prepared-request passes, whole-process results, faster compilation nor rounding the latter ratio to 1.10 changes these failures. Preserve the original reports and show the misses explicitly in release qualification. Any later changed-artifact qualification must remain distinct from this evidence.
