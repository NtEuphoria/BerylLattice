# Task 2 independent review

Reviewed immutable range `a6c5531..ad9f136` using `task-2-review-package.txt` and pinned `git show ad9f136` source. Requirements: `task-2-brief.md` and the ownership/stage-1 contracts in `docs/superpowers/specs/2026-10-17-fast-compilation-design.md`. Later ranked/compact-backend work is outside this review.

## Verdicts

- **Spec compliance: PASS for the implementation and correctness scope; performance acceptance pending final serial qualification.** The required no-more-than-10% small-case regression has not been established by this review or the Task 2 report. This is an outstanding integration gate, not evidence of a regression.
- **Code quality: PASS.** No important correctness, ownership, compatibility, or maintainability findings identified in the reviewed change.

## Review evidence

Public `check_plan` preserves its signature and routes through the original validation, fresh-source admission, identity comparison, and semantic sequence. Public native/Wasm/runtime byte APIs retain `_checked_plan` and accept no supplied proof. The internal bypass is confined to private code; the specification expressly excludes hostile in-process mutation of private state from this protocol's security boundary.

The context reconstructs exact validated Limits, admits exact immutable source bytes once, validates each actual immutable candidate, and caches canonical encoding. Candidate membership, successful receipt identity, artifact issuance, and live context membership are checked before owned emission. Cross-context or dataclass-replaced records cannot satisfy those identity registries. Closing a context clears issued authority. Service preparation closes the previous context before source validation and closes an uncommitted context in `finally`, including propagated cancellation.

The checker semantic body, original-AST expansion, every physical operation (including dead arithmetic), interval checks, grouping, equality traversal, receipt cutpoints, and accounting version are unchanged. Each check allocates its own semantic state. The private path skips only redundant admission/structural validation/encoding; structural rejection is converted through the same checker receipt path.

Legacy public and private selectors share one portfolio loop. Candidate order, reservation/charge handling, exact receipt checks, winner commit, optional-budget behavior, and incumbent retention on optional exception/cancellation remain the legacy implementation. The owned result is authorized from the exact selected receipt. The new ranked policy is deliberately not inferred here.

Native/Wasm finite lowering bodies and runtime preflight/interpretation bodies are extracted without semantic changes. Public artifact identity still hashes raw plan bytes, while owned artifacts use the canonical digest already checked. Existing storage boundaries and arbitrary valid finite-plan behavior remain in their original lowering bodies. Source AST authority remains the context's newly parsed original module, not caller metadata.

The report documents 115 passing targeted tests with actual native execution, 16 focused selection tests, and byte-for-byte baseline comparison of C/SearchResult/full compiled reports on six representative cases. These are implementer evidence, not reruns by this reviewer. The added tests directly cover ownership substitution, revocation, fresh public checking, canonical/raw identity, budget/cap receipt equivalence, structural failure handoff, preflight, and ordinary phase counts (1 admission, 3 validations/encodes/proofs, 0 internal decodes). Static inspection agrees with those counts and finds no backend recheck on the owned path.

Reviewer execution: scoped `git diff --check a6c5531 ad9f136` passed. No broad tests or performance sweeps were rerun, per coordinator instruction; no unresolved concrete issue required an additional targeted runtime probe. No implementation files were edited.
