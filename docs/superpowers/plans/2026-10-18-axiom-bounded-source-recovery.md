# Axiom bounded source-name recovery and integration

Baseline: `ebce26d9a2127540181530d0f24ada0c223e80b4`.

Implement the existing [bounded source-admission design](2026-10-16-axiom-bounded-source-admission.md) from the verified unfinished A1 archive. This is a narrow compiler foundation change, independent of the bounded presentation playground. The compact-proof F1 gate remains blocked.

1. Inspect the exact four A1 archive members and SHA-256 values; restore tests first and retain meaningful failing baseline tests. Record admission outcomes from the unchanged baseline in normal and optimized Python.
2. Restore the bounded adapter and profile integration. Preserve source identities, original AST and spans, accepted language, fixed quotas, and the bytes of `frontend.py` and `model.py`. Inspect the recovered implementation and add regressions before any corrective edits.
3. Extend O3's exact implementation inventory to the new helper. Add controls for missing helper source, changed live helper bytes, and any existing permitted bytecode cache. Qualification must reject incomplete or changed closure even when a synthetic approval graph is consistently rehashed.
4. Run normal and optimized source/frontend, source-oracle and receipt tests plus relevant reference/invocation/state checks. Compare public admission outcomes to baseline and enumerate intentional rejected-source diagnostic precedence differences.
5. Retain exact commands/results, dependency hashes, recovery provenance, and limitations for independent controller review. No commit, push, external release, O3 production qualification, or F1 approval is performed by this implementer.

The adapter's traversal counters expose actual visits/comparisons; they do not claim a complete charged compiler-work bound. A future proof accounting update must include this dependency. Source admission changes invalidate historical oracle qualification assumptions.

## Execution ledger

- Preflight: A1 changes `source_profiles` imports; O3 inventories explicit modules. The helper must join the inventory before any qualification claim. Frontend/model are shared with v1 and remain byte-identical.
- Ruling: recover reviewed-shape archived work after test-first verification, rather than discard it, because recovery is explicitly authorized. Archive provenance is evidence of origin, not acceptance.
- Baseline tests restored first: two expected failures recorded in `docs/reviews/2026-10-18-bounded-source/red-adapter.log.gz`. Raw RED logs are losslessly compressed to retain unittest's trailing whitespace; raw hashes are recorded in the compressed-log manifest.
- Initial test invocation used repository cwd with an axiom-relative PYTHONPATH and failed import; corrected invocation from `axiom/` produced the intended behavior failures. The import mistake is not treated as RED evidence.
- Differential baseline collected from an isolated baseline Git archive: 32 exact accepted matches and 27 preserved rejections in both Python modes. The initial differential script also needed `.` before `research` on PYTHONPATH to avoid their distinct `tests` package names colliding.
- Three dependency controls failed before adding the helper to O3's explicit module inventory, then all passed. A first fixture draft used an unsupported live-root name and was corrected before retaining the final behavior-failure log; the closed live-root schema was preserved.
- Ruling: product and research tests run in separate processes from their documented working directories. An initial combined command passed its 144 real tests but could not import the synthetic receipt suite because each tree owns a `tests` package. Both failed command records are retained as `initial-combined-*`; no product change addresses this launch error.
- Implementation complete: restored A1 tests and implementation retain exact archive hashes; the helper joins O3's required implementation inventory. Three additional dependency regressions pass after observed failures.
- Verification complete: 58 focused product tests and 112 focused research tests pass without skips in each of normal and optimized Python. `frontend.py` and `model.py` retain baseline hashes. Exact commands, logs and dependency hashes accompany the implementation report.
- Independent review, controller acceptance and commits remain with the parent controller. No author self-approval, production oracle qualification or compact-proof gate change is made.
