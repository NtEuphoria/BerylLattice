# Independent O3 cleanup ownership review

Reviewed the working diff in `/workspace/BerylLattice-o3-fixes` against recovered commit `6697e84`. This review covers the two documented cleanup bugs, the resulting lifecycle changes, and relevant concurrency, debt-accounting, and issuance rollback paths. It is not a production oracle qualification or a repository-wide security assessment.

## Reviewed files

| File | SHA-256 |
| --- | --- |
| `axiom/research/oracle_receipt.py` | `e80c7a7d169cd6f1c47c9e474f1076dfc0953925279123ea1c4419e9e462e1f4` |
| `axiom/research/tests/test_oracle_receipts.py` | `9a15cd1ab5b8c56a79c2ef4c78307b4f335c000a96f4e89eb1eb479df9467b0b` |
| `axiom/research/protocol/source-oracle-v1.md` | `3b13ba86bf822e5d37992e6f8d3cb4544dba04f109d249b424e050faa92c25f6` |

## Result

No remaining blocking findings in the reviewed cleanup change under the existing trusted-controller, trusted-loaded-code, stable-file contract. Full-suite validation is being performed separately by the implementing agent; this review does not claim those pending results.

The two original flaws are addressed:

- Both handle types check exact type and privately issued lifecycle state before retrying cleanup. Neither caller-writable `_closed` nor `_cleanup` is read to authorize deletion. Forged objects and copied public state cannot create a cleanup record.
- Parent closure transfers failed child cleanup responsibility and clears pending child path claims. It coalesces scratch and other debts into enclosing cleanup roots. Successful removal retires owned descendants; a later close cannot reclaim the same path after reuse. External producer debts remain independently retryable if scratch removal succeeds first.

All retries use the original session lock. Lifecycle records are allocated when handles are issued, avoiding new tombstone allocation after authority invalidation. The weak registry holds values that do not reference their key handles or qualification records. Failed issuance may temporarily retain an unreturned handle through an exception traceback, but does not publish verification authority or permanently retain the handle through the cleanup registry.

Preparation of deletion-path and debt-retirement lists precedes removal. Successful path removal immediately consumes the retry entry. Child debt release removes the corresponding pending close and decrements retained accounting once. Parent closure preserves global cleanup debt until its remaining owned roots are removed.

## Finding resolved during review

The first patch trusted a child authority lookup made before acquiring the session lock. A paused second close could resume after another thread had already closed the child, requeue the retired directory, and then raise `KeyError` while removing the already-removed issuer entry. A subsequent retry could delete caller data at the reused path.

The final patch repeats `_oracle(self)` inside `_operation(selected)` before changing cleanup state. The added deterministic test pauses the initial lookup, closes and reuses the path from another thread, then resumes the stale close. It checks rejection, preserved caller data, and absence of newly queued cleanup debt. The implementing agent reproduced the initial failure and reported the corrected test passing.

## Validation and limitations

This reviewer inspected the production and test diff, the original protocol, and the recovered unfinished regression tests. `git diff --check` passed. The seven added test methods cover both original failures, caller-field tampering, partial parent cleanup with external debt, reentrant child retry, concurrent closed-parent retry, and the stale child-close lookup race. Expensive suites were not rerun by this reviewer.

No claim is made about hostile same-UID path replacement, reflective mutation of private issuer tables, interpreter or OS compromise, native admission, independent production approval, or O4/O5 acceptance. Those remain outside this change and the existing O3 boundary.
