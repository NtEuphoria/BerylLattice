# Bounded v2 source-name admission

Implemented against `ebce26d9a2127540181530d0f24ada0c223e80b4` on October 18, 2026. Independent review and controller acceptance are separate from this implementation record. The [recovery implementation plan](../superpowers/plans/2026-10-18-axiom-bounded-source-recovery.md) applies the existing [A1 design](../superpowers/plans/2026-10-16-axiom-bounded-source-admission.md).

## Contract and preservation argument

V2 admission still starts with fresh exact source bytes and returns the original parsed module. Before the existing shared validator/profile functions run, a private view maps semantic names injectively to at most nine one-character ASCII aliases. The registry scans each resident spelling at most once per occurrence, checks lengths first, and compares equal-length strings character by character. It stores at most nine original strings and never hashes, sorts, or compares whole original names as registry keys.

The admitted family has five global declarations and four bound-axis roles. Distinct spellings receive distinct aliases; repeated spellings retain the same alias across namespaces. Thus declaration equality, lookup, local shadowing, declaration order, tensor/index namespaces, and source dependence retain their existing meaning. Only declaration names, axis names, name references, and tensor-read names change in the transient view. Shapes, literals, grouping, child order, types, properties, objectives, source bytes and spans remain unchanged. Categorized tuples refer to the rebuilt declaration objects rather than independently copied trees. The returned admission result retains the original module and identity construction.

Necessary declaration-count, literal-shape and rank guards now precede general constant/index validation. Every previously admitted v2 source already satisfies these guards. They avoid unsupported shape chains and ranks entering unrestricted validation. A tenth distinct semantic spelling is rejected at its original span. Diagnostics quoting aliases translate once to original names, including names that themselves resemble aliases; private alias exceptions are suppressed as context.

The shared `frontend.py` and `model.py` remain byte-identical. Source/profile/identity limits are unchanged. V1 admission and identities are untouched. No Core, planner, checker, native, or source-oracle execution implementation is changed.

## Oracle dependency closure

`oracle_receipt._REPOSITORY_MODULES` now includes `axiom.source_names_v2`. Existing O3 inventory machinery binds its source and any existing permitted bytecode cache. Three fresh controls establish that the helper and cache are enumerated, a consistently rehashed synthetic approval omitting the source is rejected, and changing live source/cache bytes invalidates selection and revalidation.

Live mutation tests operate on owned temporary copies under the repository live root and temporarily substitute module metadata within the test process. They never modify the loaded repository source or execute fixture cache bytes. The temporary approvals contain explicit fictitious execution/review assertions; they test policy mechanics only.

## Recovery and verification evidence

The four A1 archive members were checked against `recovery/unfinished-work-manifest.json` by exact path, regular-file type, byte length and SHA-256 before restoration. Tests were restored before implementation. Two baseline controls failed because the adapter was absent and original long names reached validation. The restored adapter then passed all ten name-boundary tests. Three new O3 controls failed before the dependency inventory change and passed afterward. The four restored A1 files remain byte-identical to their archive members.

An isolated `git archive` of the baseline supplied the old admission implementation for differential comparison. The same corpus recorded 32 accepted and 27 rejected sources in normal and optimized Python. All accepted records matched exactly, including original AST representation hashes, exact source, dimensions, constraints/objective and every admission identity. All rejections remained rejections. Baseline and integrated normal/optimized records each matched exactly.

Seven rejected-source diagnostics intentionally changed: input/producer/output rank, a missing shape, conflicting negative/nonliteral shapes, an undefined name combined with an extra shape, and a tenth semantic name. The necessary early guards or bounded-name rejection now report `UNSUPPORTED_PROFILE` first. Every exact before/after diagnostic is retained in [differential-summary.json](2026-10-18-bounded-source/differential-summary.json).

Fresh integrated verification passed 58 focused product tests and 112 focused research tests in each of normal and optimized Python, with no skips. These cover source names/profiles, frontend, reference evaluation, invocation/blob transport, state artifacts, the original-source oracle, O3 and synthetic receipts. Exact commands are recorded in [verification.json](2026-10-18-bounded-source/verification.json). Full product/research suites and native Core checks were not rerun by this implementer; controller integration verification is separate.

An initial command combined the two trees' separate `tests` packages: its 144 real tests passed, but synthetic receipts failed to import `tests.test_manifest`. Both failed launches are retained. The final passing commands use the documented separate working directories. The evidence directory also retains failing/passing regression logs, complete focused-suite logs, differential inputs/outputs, recovery inspection and final dependency hashes. The implementation reviewer should inspect those exact final bytes rather than infer acceptance from historical records.

## Remaining boundaries

This change repairs the bounded name-resolution prerequisite. Its counters describe actual adapter traversal and comparison work, not a complete charged compiler-work bound. Fixed-alias shared-map work, complete source/graph costs and the full rule-payload semantic replay still need reconciliation in P1/P2. F1 remains blocked and the fixed quotas have not been relaxed.

No production O3 qualification, independent approval, native eligibility, scalability result, speedup or publication claim follows from these tests. Qualification requires the final implementation/runtime closure, real retained execution evidence and independent review/approval. Historical qualification assumptions do not cover the revised dependency bytes. The independent controller owns final acceptance and integration.
