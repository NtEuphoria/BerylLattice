# Axiom v2: deterministic source-name admission repair

Date: 2026-10-16. Baseline: `d7e22c857ccf681cc94af9a1bfdf98282899b02c`.

This is a narrow prerequisite amendment to the [proof/oracle continuation](2026-10-16-axiom-proof-oracle-continuation.md), authorized by the ongoing plan-and-build request. It repairs a demonstrated accounting gap; it does not raise a quota, broaden the admitted family, or approve C1. The [continuation design](../specs/2026-10-16-axiom-proof-oracle-continuation-design.md) and scalability master remain authoritative.

## Problem and chosen repair

Current C2 passes arbitrary original identifier strings directly to the shared frontend's dictionaries and sets. CPython perturb probing can revisit a resident key: an eight-slot table and hash 32 can probe 0,2,3,0. Charging a fixed structural probe allowance plus one byte comparison per resident therefore misses possible repeated long-string comparisons. A candidate-scan bound is not an upper bound on that implementation.

V2 will build a private alpha-renamed view of its freshly parsed module. A deterministic linear registry compares each original semantic name to each resident spelling at most once per occurrence, assigning one of nine fixed one-character ASCII aliases. The existing, byte-unchanged `_validate` and `_profile` operate on this view. Their dictionary keys then have fixed length. The result retains the original parsed module, exact source bytes, digest, groups, scalar association and spans. H/W and normalized roles come from the validated view. No second semantic validator is introduced.

The global renaming is injective on distinct source spellings and preserves identical spellings across namespaces. This preserves declaration uniqueness, references, dependency order, local axis shadowing, and tensor/index namespace distinctions. Rename only declaration names, axis names, `NameReference.name` and `ReadExpression.name`. Do not rename module names, element types, properties, operators, objectives, literal values, kind tags or source bytes. Original-name strings must never enter the shared validator/profile name maps through this view.

The exact supported family has five global declaration roles and four axis roles, at most nine distinct semantic names. More than nine is outside the family, even when local names shadow global names or the two equations reuse axis names. The registry rejects a tenth distinct semantic spelling, with a source diagnostic and original span. It does not retain an unbounded dictionary or hash arbitrary original names. Each comparison includes an explicit length check and at most the shorter spelling's bytes; compare a candidate at most once. Any accounting helper must report actual traversal/comparison work, not imply a complete C1 bound.

Before invoking general constant/index validation, v2 checks the necessary exact counts (two shapes, one input, one producer, one output), literal-only shape declarations after groups, input rank two and both equation ranks two. These checks exclude no previously accepted v2 source. They prevent unsupported declaration chains/ranks from reaching unrestricted semantic work. This can change which diagnostic is reported for an already-rejected source with multiple errors. Record that v2 diagnostic-order change explicitly. Preserve existing codes/spans for supported-shaped ordinary failures and existing tested rejections wherever the early guards do not preempt them. Validator diagnostics that quote a private alias must be translated back to the corresponding original name without cascading replacements; errors must not expose private aliases as source names.

Parsing remains the existing bounded parser. Decoder ingestion and semantic name resolution remain distinct: the latter stays in the semantic work budget. The existing source-byte, token, node and nesting limits are unchanged. Early shape-literal guards remove arbitrary source-declaration constant-growth chains; other rejected expressions remain bounded by source size, ten-digit literals and parser depth. This repair does not itself establish C5's hostile-candidate charge-before-work checker. Its accepted-source cost must be reconciled by P1, and decoder policy still needs independent P2 review.

## Ownership and dependency graph

| Task | Prerequisites | Sole owned files / interfaces | Completion evidence |
| --- | --- | --- | --- |
| A0 repair preflight | source-work audit and this design | controller: this plan and continuation task table; independent reviewer: ignored report | semantic preservation, accounting and ownership review |
| A1 bounded adapter | A0 | implementer: `axiom/src/axiom/source_names_v2.py`, `axiom/src/axiom/source_profiles.py`, `axiom/tests/test_source_names_v2.py`, additions to `axiom/tests/test_source_profiles.py` | meaningful RED/GREEN, exact fresh-byte boundary, unchanged accepted identities/original AST, deterministic-name controls |
| A2 admission acceptance | immutable A1 checkpoint | independent reviewer report; controller acceptance record | SPEC/QUALITY review, differential and adversarial checks, v1 byte identity |
| A3 dependency reconciliation | A2 plus P1/O3 readiness | P1 owner: own accounting/graph files; O3 owner: already-owned `oracle_receipt.py`, tests and protocol; controller: integration record | revised actual cost argument, complete new dependency inventory and fresh C2/O2/O3 regressions before any new qualification |

A1 may run alongside P1 and O3 because their write sets are disjoint. Neither concurrent owner edits these admission files. All tests must record the C2/dependency revision they actually used. The controller serializes commits. Source admission acceptance invalidates any assumption that earlier O2/O3 tests exercised the new dependency; rerun their relevant suites at the integrated checkpoint. No production qualification root is constructed until final dependency bytes are fixed and reviewed.

O3's current `_REPOSITORY_MODULES` inventory is explicit. A3 must add the actual `axiom.source_names_v2` execution dependency, including its source and any permitted existing `__cached__` file, under the O3 owner's existing module ownership. Add controls that omit or alter the helper and require qualification/revalidation rejection. Code that executes the helper with an inventory that omits it cannot qualify, even if earlier fixed-list tests pass. The fresh O3 reviewer must inspect this final dependency-closure change.

Do not edit `frontend.py`, `model.py`, v1 interfaces, source oracle implementation, invocation/state APIs, Core, native code, fixed quotas or the tracked C1 gate. If implementing this adapter needs any such change, report the concrete conflict for controller reconciliation rather than silently expanding ownership.

## A1 implementation sequence

1. Retain a failing test that demonstrates the missing bounded adapter and expected original-AST/identity contract. Add a second failure that checks shared `_validate`/`_profile` receive only fixed aliases when original names have long equal prefixes. Tests should inspect that boundary rather than depend on finding a random hash collision.
2. Implement the bounded linear registry and private view builder. Traverse `module.declarations` once, rebuilding categorized tuples from those same declaration objects; do not independently revisit duplicate categorized AST references. Preserve all group nodes, binary child order, declaration order, coordinates and original spans. Avoid general serialization/reparsing and no semantic simplification. A tiny fixed-list alias table and bounded original-name comparisons are sufficient; do not use `dict`, `set`, sorting, string hashing or object-wide string equality over original names as a hidden alternative registry.
3. Insert necessary shape/cardinality/rank guards in v2 `_admit`, then build the view, validate it, extract H/W from its shape declarations and normalize it. Construct `AdmittedLoopKernel` from the original module and existing identity payloads. The public function and constructor signatures stay unchanged. Existing constraint/objective validation semantics remain unchanged.
4. Translate original-name diagnostics through an exact noncascading mapping. Document private-view invariants and the accepted-language preservation argument in code and the implementation report. Keep helper API private to v2; no caller-created view becomes admission authority.
5. Reconcile fixed-length shared-map probe work with the independently audited CPython model. The adapter removes repeated *long* comparison work; it does not turn every Python operation into one unit. Supply the exact new call-site inventory to P1. P1 must pay adapter visits/copies, original-name scans, original-source identity, constraint/group work and retained-axis artifact bytes. Finite samples corroborate, never establish, the family bound.

## Required verification

Use the existing public v2 source API for acceptance tests, plus private helper controls for the bounded registry. Retain exact old baseline outcomes/identities for differential comparison in an isolated Git archive; do not import a second live implementation under conflicting module names.

- Canonical 1x1, 5x7, 32x32, 2048x2048 and both profile boundary rectangles and transpositions; no tensor allocation.
- Existing v1 golden identities and all v1 source tests, with `frontend.py` and `model.py` byte-identical to baseline.
- Renamed globals, distinct/reused equation axes, allowed cross-namespace spelling reuse, shape/axis shadowing, groups around shape literals and indices, interspersed/repeated constraints, all objectives, comments/whitespace and maximum source length. Compare all existing v2 identity fields; exact source must remain exact.
- Original parsed module equals the retained returned AST, including every original name/span/group/order. Fixed aliases reach shared validators, including nested names and all categorized/declaration references; no original long identifier leaks into a validator key.
- Long equal-prefix spellings, one very long output name, equal text in different occurrences, differing-length names, ninth and rejected tenth distinct semantic name. Assert at most one comparison per resident per lookup and bounded registry storage. Do not freeze incidental Python dictionary iteration or random hash seeds.
- Duplicate globals/axes, undefined shape/tensor/index, illegal forward/self references, shadowing that changes a computation, changed scalar association, wrong literal/operator/read, wrong ranks/cardinalities and nonliteral shape chains. These remain rejected. Record intentional diagnostic-order differences from necessary early guards.
- Public typed configuration forgeries/tightened source/parser limits still reject. No supplied AST or alias map bypasses fresh parsing.

From `axiom/`, run normal and optimized Python:

```sh
PYTHONPATH=src:research python -m unittest discover -s tests -p 'test_source*.py' -v
PYTHONPATH=src:research python -O -m unittest discover -s tests -p 'test_source*.py' -v
PYTHONPATH=src:research python -m unittest discover -s tests -p 'test_frontend.py' -v
PYTHONPATH=src:research python -O -m unittest discover -s tests -p 'test_frontend.py' -v
```

At A3, run accepted O2 source-oracle tests and relevant reference/invocation/state dependencies in both modes, plus O3 focused tests against the final source bytes. Repeated 2048 oracle execution is unnecessary unless source interpretation/output changes or a new concern warrants it; the existing large control remains pinned to its historical accepted commit.

## Acceptance and evidence

Retain tests, failing-first logs, focused pass logs, differential results, exact dependency hashes and a report in `.superpowers/sdd/axiom-checked-execution/`. A fresh reviewer independently checks the implementation and alpha-equivalence argument at the immutable commit; no author self-approval. Controller records actual acceptance and dependency re-review.

A2 approval establishes the repaired C2 boundary only. P1/P2 still must close complete rule-payload accounting, source/graph/byte recurrences and all frozen quotas. C1 remains blocked until that separate mathematical review approves. O3 and native/performance eligibility remain independently gated.
