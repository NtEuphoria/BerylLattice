# Axiom scalability implementation record

This work implements the [reviewed scalability plan](superpowers/plans/2026-10-16-axiom-scalability/README.md).
Axiom remains the confidential 5GL research project; Core remains the separate
4GL language. This record distinguishes implemented boundaries from later
proof, execution, measurement and publication gates.

## Completed foundations

| Task | Implemented result | Verification and limits |
| --- | --- | --- |
| G0 | Preserved the plan and source inventories; verified recovery through a clean local bundle clone | Portable setup passed; existing toolchain receipt revalidated. Independent cloud-task restoration remains unverified. [Baseline record](reviews/axiom-scalability-baseline.md). |
| G1 | Reconciled shared ownership and dependency order before implementation | Independent preflight covered 46 task/gate entries and 438 shared-interface/file pairs. This is contract review, not proof or native qualification. |
| C2 | Explicit fixed-buffer source admission, retained original AST, separate source/family/specialization and policy identities | Commit `958de943aeba6f8fd00dd983924499c6ca32a85c`; 33 focused/frontend/reference tests and 21 optimized-Python checks passed. Independent specification and quality review passed with no findings. An additional admission-only overlap probe passed all 955 v1 shapes across three policy settings (2,865 cases). |
| B1 | Executable test-only boundary contract and independent tiny Core fixtures | Commit `aaa6d2f2c87ff47ee15c7f4f0bc809a45846831c`; 14 tests passed normally and under optimized Python. Three deliberately bad adapters failed. Independent specification and quality review passed with no findings. No native claim. |
| B2 | Actual pinned Core emission linked to a private typed C host, with complete valid/rejected tiny observations | Commit `cf01790ca3fa97e22e60a842427a3c582dec5a5b`; 13 native tests passed normally and under optimized Python, plus 50 related regressions. Independent specification and ABI/quality review passed. Both runs used C `-O0`; Python optimization is not native optimization. G2a passes for this fixture. |
| B3 | Owned input/output handles and operation scratch, checked extents and generations, preflight ordering and original-owner cleanup | Commit `9912ead6c330fb0f302e687aca577fecad005bc0`; 18 combined B3/B2 tests passed normally and under optimized Python, including actual ordinary, ASan/UBSan, LSan, allocation-interception and fault controls. Independent specification, ABI/quality and ownership review passed. B3 native tests use C `-O1`; B2 remains C `-O0`. |
| O1 | Bounded chunked blobs and exact-source invocation transport with fresh source and storage validation | Commits `7e72feeed82648b059e6f9884a2ebc56cf0a27a0` and `64da9e296f6c82f11ce5410c1421677fc6fc990f`; 14 focused tests and 28 frontend/state regressions passed normally and under optimized Python. Independent specification and quality review passed after strict typed-record validation and standard-suite import fixes. |
| O2 | Original-source AST streaming oracle with complete preflight, private bounded input snapshot, full state preservation and atomic completion publication | Commit `eeb8f2c8e247d42abc73c6727ddfed57ab99a1d9`; independent specification and quality approval. 29 focused tests in both discovery modes, 51 dependency regressions and 29 additional reviewer controls passed normally and under optimized Python. A disclosed 2048×2048 all-max control checked every input/output value with a 2 MiB input cache. [Acceptance and evidence](reviews/axiom-source-oracle.md). |

The [source-profile guide](../axiom/docs/loop-plan-v2.md) describes the new
`admit_source_v2` API. Its fixed dimensions are in `1..8192`, with at most
`2^23` input cells. Admission does not allocate those buffers or prove that a
physical plan is correct. Existing v1 source limits, identities, commands and
native performance admission remain unchanged.

## Open gates

C1 independent review accepted the written conditional induction argument but
keeps feasibility blocked on complete hand-certificate representation and
fully charged quota bounds. The follow-up at
`00dd07949d6fa32437c53460cf6a340d8f85567e` corrected the peak scratch-fact count
and made the gap explicit; independent review accepted its accuracy, not
positive feasibility. Its proposed 440,352-byte allocation depends on
uninstantiated capacities, while its conservative work estimate is 8,814,588
against the unchanged 1,000,000-unit allowance. Neither number proves a complete
certificate fits; the excessive upper estimate also does not prove impossibility.
Eleven research controls passed normally and under optimized Python.

The scalable original-source oracle is now implemented and independently reviewed;
its O3 qualification and the production loop checker remain separate requirements.
The first integrated native target remains a checked 32×32 computation
through Core with complete independent result comparison, then the disclosed
2048×2048 training shape.

Separate sanitizer prerequisites now pass clean and faulty ASan/UBSan/LSan
witnesses using an authenticated runtime package in a scratch resource prefix.
The qualified compiler installation is unchanged. This does not qualify the
application host or its memory lifecycle by itself. B3 separately ran the actual
host and allocator through those sanitizers. Its allocation interception covers
direct linked calls in the tested tiny executable; shared-library internals,
direct syscalls and other kernels remain outside that coverage. An actual
`mmap` control demonstrates this limit. Complete allocation accounting remains
unqualified, and balanced allocator counters do not establish stable RSS.

The [invocation protocol](../axiom/research/protocol/invocation-v2.md) records
the transport's stable-file assumption, two-chunk cache, repeated full-byte
validation and per-scalar reopen/stat cost. Declaring the owned-buffer contract
does not establish actual native ownership or successful execution.

Native timing admission, performance results and paper readiness remain later
gates. No scalable native execution, speedup, general language capability or
machine-checked soundness theorem is claimed by the work recorded here.

## Integration verification

The [independent integration review](reviews/axiom-scalability-foundations.md)
passes this foundations checkpoint. It does not approve C1 feasibility or the
full scalability milestone.

| Check | Actual result |
| --- | --- |
| Standard product discovery, `PYTHONPATH=src python -m unittest discover -s tests -v` from `axiom/` | PASS: 239 tests, 12 explicit skips, 356.639 seconds, exit 0; immutable `64da9e296f6c82f11ce5410c1421677fc6fc990f` source snapshot. Receipt: `/workspace/scratch/axiom-foundations-product-pl7g5502/receipt.json`. Native selectors were unset; skips are not native qualification. |
| Full research discovery, `PYTHONPATH=.:../src python -m unittest discover -s tests -v` from `axiom/research/` | PASS: 97 tests, 122.864 seconds, exit 0; immutable `7e72feeed82648b059e6f9884a2ebc56cf0a27a0` snapshot. Receipt: `/workspace/scratch/axiom-foundations-research-0d4albds/receipt.json`. Later changes do not alter the tested research implementation/dependencies. |
| Actual B3/B2 native tests | PASS: 18 tests normally and under optimized Python, with explicit qualified Core/Clang and sanitizer inputs. Final evidence: `/workspace/scratch/axiom-B3-native-lifecycle/axiom-B3-pj_wtn5v` and `/workspace/scratch/axiom-B3-native-lifecycle/axiom-B2-binding-v5o86r0u`. |
| Compatibility and documentation | Baseline v1 implementation bytes unchanged; Core clean at `0a678b4ae6d41190c4f5a8bf063caba05759d20d`. Local documentation links, code-fence balance and whitespace checks pass. The qualified Core receipt still records its two known baseline unit failures. |

The initial broad product run exposed a B3 test-helper cap error and an O1
test-import error. Both were corrected and the full standard command above
then passed. O1's independent review also found equality-based acceptance of
forged typed metadata; explicit nested type checks and negative controls now
resolve it. The separate C1 finding remains open.

## Next implementation sequence

1. Resolve C1/F1 with complete scoped hand graphs for inline, materialize and
   rows2, or a proven complete expansion. Enumerate reachable term, affine and
   substitution instances; charge every premise, memo lookup and integer
   operation. Bind the argument to exact artifacts and obtain another independent
   review. Quotas remain unchanged; C4–C11 cannot start on the current evidence.
2. Once that gate passes, settle the C3 encoding against the concrete graphs and
   build the C4/C5 independent checker. O2 is complete; O3 qualification and
   expected-state binding can proceed independently under the
   [reviewed O3 plan](superpowers/plans/2026-10-16-axiom-oracle-qualification.md).
3. Integrate checked emission, qualified native builds, owned invocation and
   complete independent state comparison. Pass the disclosed 32×32 case before
   the planned large-case campaign; performance measurement stays a later gate.

## Execution rulings

1. Use the existing isolated cloud checkout on `work`; verify recovery in an
   ordinary scratch clone. Local restoration does not establish cloud
   publication or remote persistence.
2. Implement C2 before B1 executable contract tests. The native lane consumes
   the sole source-admission API.
3. Keep B1's observable ordering adapter explicitly test-only. B3 owns the
   production lifecycle; B2 supplies actual compiler/executable evidence.
4. Serialize shared source, document ownership and commits. Independent tasks
   may proceed on disjoint files under the developer delegation guidance and
   the reviewed plan. Every product task gets
   independent specification and quality review; focused tests precede broader
   integration checks.
5. Stage the native inventory dependency through O1's production-safe blob API,
   then B5's build inventory, then O4's complete store verification. Production
   code must not import the research verifier or future timing capability.
6. Assign the required straightforward scalar Core comparator to M5a, with
   B4/B5 boundary review. It is a separate experimental control, not a fourth
   generated portfolio plan.
7. Preserve the actual training, pilot, freeze and final-measurement chronology.
   Implemented admission machinery does not imply collected experiment evidence.

The detailed ledger, briefs, reports, review diffs and test logs live under
`.superpowers/sdd/axiom-scalability/` for the foundations and
`.superpowers/sdd/axiom-checked-execution/` for this continuation. Recovery archives retain them at
integration boundaries. The original prototype's completed evidence remains
in its separate [implementation record](implementation-record.md).
