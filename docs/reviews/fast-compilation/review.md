# Independent design review

Baseline inspected: `39dc2f6df136c643cfd030ce4470503e807750fe`. Review scope: architecture, implementation plan, primary-source fidelity, bounded-loop correctness and measurement interpretation. This is review of a proposal and diagnostic evidence, not qualification of unimplemented compiler code.

## Review outcomes

| Reviewer scope | Finding | Resolution |
| --- | --- | --- |
| Compilation ownership and search | Original eight-validation count applied only when all three candidates are eligible | Documents give conditional counts: six/seven/eight; raw browser counts retained |
| Compilation ownership and search | Stop behavior needed every UNKNOWN reason, and accounting needed distinct step/allocation quotas | Policy stops on all candidate-stage UNKNOWN; optional hint fallback is separate; accounting text distinguishes `check_steps` and `expression_nodes` |
| Bounded loop/correspondence | Syntax and primitive-op limits do not bound empty-loop traversal | Separate hint traversal/index/SSA work quota, checked saturating preflight and per-step charging; explicit empty-body/zero-trip tests and typed fallback |
| Literature and benchmark interpretation | A fresh Worker can share browser-native Wasm module cache | Engine-cold qualification requires fresh browser process/temporary profile or verified cache control; runtime boot separate; no user-program warmup |
| Literature and source fidelity | No unsupported paper-to-Beryl speedup or unbounded-proof claims found | Seven primary sources retained with precise claims/limits; proposed architecture and targets explicitly unmeasured |
| Final bounded-loop/evidence review | No further material findings after fixes | Reviewer confirmed traversal fix and measurement-scope/reproduction narrative |
| Final literature review | No outstanding material findings after fixes | Reviewer confirmed cold-cache fix, citation fidelity and unchanged original source manifest |

The reviewers agreed on the staged sequence: owned context/handoff, versioned ranked checking, bounded correspondence, compact backends, then residual-driven experiments. Current arbitrary finite plans, exact byte identities, forged-record rejection, preflight/failure behavior and the blocked scalable-v2 gate remain explicit obligations.

## Checks performed for this research change

- CPython diagnostic probe completed all six shape/cap cases, seven unprofiled preparations each plus separate cProfile runs.
- Real Clang compiled/linked both actual 15×15 plans at O1/O2/O3, five rotating samples per flag/plan; all thirty executable outputs passed the external ramp formula audit. Both compiler-only traces retained. Kernel throughput was not measured, so no flag change is recommended.
- Real Chromium/Pyodide completed twenty instrumented fresh-source preparations. Every emitted module executed and passed an external stencil formula check. Separate call-count profiles confirmed four checks/seven admissions and conditional encode/validation counts.
- Copied browser harness/input integrity check passed: HTTP/local inputs equal, public ZIP/member hashes match release manifest, and retained harness scripts match recorded hashes.
- Eight retained JSON files parsed; Python probe scripts passed AST parsing and four JavaScript harness/Worker files passed Node syntax checks. Relative documentation links resolved after the review file was added.
- All 26 baseline compiler Python module hashes remained unchanged. Downloaded primary-source hashes matched the access manifest. Git whitespace checks passed after staging.

The full production test suite was not rerun for a documentation/research-only change with unchanged compiler source. Existing implementation test results belong to the [previous compiled-execution record](../compiled-execution/README.md). New implementation stages must perform the tests and controlled latency/throughput qualification in the plan; prior results do not establish their correctness or targets.
