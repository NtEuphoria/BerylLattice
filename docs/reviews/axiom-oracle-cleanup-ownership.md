# O3 cleanup ownership follow-up — 17 October 2026

The recovery checkpoint `6697e84` contained two cleanup defects. An exact-class
forged handle could set `_closed` and `_cleanup` to delete a caller directory.
Separately, a child whose cleanup failed retained its path after parent cleanup
removed the enclosing scratch directory; retrying the child could delete new
files created at the reused path.

This follow-up fixes those lifecycle defects. It does not establish full O3
oracle qualification or native performance admission. The unchanged recovery
archives continue to describe the historical baseline, including its defects.

## Ownership and retry behavior

Cleanup authority now lives in private lifecycle records created when handles
are issued. Each record retains the original session lock, its closed state,
and its remaining cleanup roots. Exact object identity selects the record;
caller-writable handle fields cannot choose cleanup paths or bypass validation.
The registry uses weak keys, and its values do not retain their handle keys.

Every retry uses the original nonblocking session guard, including retries after
the qualification has closed. Live child authority is checked again after
acquiring that guard. Parent closure transfers pending child cleanup to the
parent and removes descendant paths from the cleanup queue when an enclosing
owned root covers them. External producer debts remain separate and retryable.
Successful removal consumes the path claim and releases retained debt once.

Lifecycle records are allocated during issuance, before authority publication.
Cleanup prepares path and retirement lists before deletion, then consumes the
successful path immediately. Existing issuer registration rollback remains in
place. These changes preserve the protocol's trusted controller, loaded-code,
and stable-file assumptions.

## Regression evidence

The two recovered unfinished regression tests were reproduced against the
baseline before applying the fix. Five additional tests cover related lifecycle
boundaries:

- Mutating fields on genuine live or closed handles cannot redirect cleanup.
- Parent scratch removal followed by external cleanup failure cannot leave a
  stale child path in either the child's or parent's retry queue.
- Closed child retries cannot reenter an active qualification operation, and
  successful retries release storage debt only once.
- Concurrent closed-parent retries obey the original session lock.
- A child close paused before lock acquisition cannot restore cleanup authority
  after another thread has already closed the child and the path is reused.

The last race was identified in independent review of the first patch. Its test
failed with a stale issuer-table `KeyError`; checking child authority inside the
session guard corrected it. All seven new test methods have recorded failing
and passing runs. The additional lifecycle RED run initially exposed test
cleanup contamination; the retained final RED log contains only the intended
behavioral failures, with test cleanup restored between cases.

## Review and verification

The [independent review](2026-10-17-o3-cleanup/independent-review.md) records exact
source, test, and protocol hashes, the resolved concurrency finding, and no
remaining blocking findings within this change's scope. The implementing agent
verified those hashes before retaining the report.

[Verification results and artifact hashes](2026-10-17-o3-cleanup/verification.json)
bind the full product suite, full research suite, optimized-Python oracle and
receipt checks, regression logs, and independent review to the changed files.
Commands are recorded with their working directories and exit codes. The
baseline O3 suite passed 31 tests; the new O3 suite adds seven tests.

The portable product suite has documented optional-native and lost-receipt
skips. This change does not modify Core, rerun its native qualification, or
resolve its two previously recorded unit failures. Python `-O` verification
checks assertion-independent behavior and is not native compiler optimization.

## Remaining qualification work

O3 unit fixtures explicitly use synthetic approval assertions. Passing them and
reviewing this patch do not generate a real retained qualification closure or
external approval. The changed oracle module has a new implementation identity;
old qualification evidence cannot approve these new bytes. Real execution logs,
complete retained input/runtime identities, review, and explicit approval of
that exact closure are still required before production oracle qualification.
