# Independent recovery audit

Final status: no remaining blocker found for presenting the audited export as an
incomplete, transparently labelled recovery checkpoint. It is not resurrected
Git history, proof of the complete original checkout, or newly approved O3 work.

This audit examined reconstruction and selection integrity, historical
provenance, unfinished-work separation, exported bytes and modes, and known
source gaps. It did not execute recovered application tests. Functional test
outcomes belong to the controller's separate validation record.

## Final audited snapshot

- Tree: `staging/recovered-tree`.
- Manifest: `staging/selection-manifest.json`.
- Manifest SHA256: `2cb5f707d7b9f43cf2acdb09f2ed3af0f00f01e596ba5fc2c05290004d042882`.
- Reconstruction engine SHA256: `30838caef6a40e6bd8fb534e58528da982429bd41431a486e020b7de1a612f15`.
- 281 selected files, including 224 historical paths under BerylLattice;
  4 ambiguous internal review/task paths withheld; 60 candidate versions
  quarantined. These are exported-file counts, not Git-tracked-file counts.
- Current indexed evidence: 168 input files, including 161 retained history JSON
  files, and 650 indexed candidate versions. All input and candidate hashes and
  sizes matched when checked. The engine hash matched the index.
- Earlier audited v2 manifest:
  `324d993d633c236e1bd00a0867e1fd9dd78cf0501c20678ea0749d106aa344a6`.
  The final export above supersedes that preliminary snapshot.

## Findings resolved during recovery

1. **Unfinished-work exclusions could be overridden.** The original selector
   tested `restore_eligible: false` per provenance record, allowing identical
   bytes through a raw addition, heredoc, or replay record. Earlier P1 versions
   could also survive when only their final candidate was excluded. The revised
   selector vetoes the exact path and digest when any provenance explicitly
   excludes it, and excludes all versions of the newly introduced unfinished
   P1/A1 paths. The final tree contains no such path or selected vetoed record.
   Prior committed C2 profiles/tests and the earlier loop-plan document remain.
2. **A documentation seed used the wrong earlier base.** Selected prototype hash
   `2841fb2...` silently omitted the accepted canonical-plan replay paragraph.
   Independently applying root patches 498/501 to the explicitly hash-bound,
   Git-verified base `2f62687...` produced `56590e9191d354f15a6fa48a599f82563566f3bccea7cd222a9325361a7a2b2f`.
   The wrong seed is now vetoed; the final export selects this corrected result.
3. **Combined-command success masked failed file creation.** Two nonexistent
   paths had been promoted from heredocs despite explicit shell redirection
   failures: root `protocol/experiment-v1.md` and nested
   `axiom/research/axiom/research/tests/test_manifest.py`. The engine now records
   the relevant creation failure, and both phantom paths are absent. Canonical
   research protocol and test files remain. An independent scan reviewed 12
   selected provenance/event references with failure-like output. Other hits
   concerned failed launches followed by identical successful writes, log
   redirections, test behavior, or quoted source text; no further selected
   creation failure was found.
4. **Evidence wording overstated command execution and cmp success.** The engine
   does not execute historical commands, while a separate fixture script imports
   recovered helpers to regenerate a fixture. Documentation now distinguishes
   these methods. Fixture append provenance also now says that a historical
   `cmp` was invoked but its separate exit status was not recorded; the final
   command's zero status alone did not prove that `cmp` succeeded.

## Independent checks performed

- Enumerated the final tree and checked exact membership, every SHA256, byte
  size, and mode against its manifest. No extra/missing files, mismatches, or
  symlinks were found. Scanned selected bytes for tool redaction placeholders
  and selected provenance for excluded candidates; no violation was found.
- Rechecked all current input and candidate hashes and the engine/index match.
- Earlier selected recorded-SHA claims were checked against path-associated
  historical command output: all 34 matched. All 32 selected historical Git
  blob-prefix provenance records in v2 were recomputed and corroborated against
  path-associated historical diff headers. The later core-bridge replacement
  separately matched logged blob `411f7723496e28d84ead00f19e189f8c8234a33a`.
- Independently reconstructed integration `test_core_correspondence.py` from
  its complete original addition and five ordered patches, enforcing exact
  hunk positions, old bytes, and counts. Result:
  `cca8ba87be27d9395137ea37348c78696f0f8a7c2e75d6857c6be4ec256fb719`.
- Independently reconstructed the architecture review from its complete add
  and six ordered patches. Result:
  `6a1026faa1e436e73ff6702d96a1c234463437928a9c53dc5d9de4652d78a807`.
  Its selected provenance does not claim an independently printed final digest.
- Independently checked both root prototype patches from the accepted base;
  the corrected final digest is recorded above. Two selected scratch documents
  equal their complete single-file cat outputs exactly. The selected scratch
  research-program version matches its final patch applied to the complete
  earlier observed/addition bytes.
- Recomputed the complete literal heredoc for `test_core_observe.py` as
  `34fbe6a4dd5961c017282f5b3d7774c85e6caf98cf4f53db0cf7b435cf08a7a4`.
  Historical execution failed with exit 1 because the dependency had not yet
  been created; its traceback reads the exact new test path at line 3. This
  supports the narrowly documented successful-write exception while preserving
  the combined command's failed status. It does not mean the historical test
  passed.
- Independently appended the exact retained heredoc bytes to the original
  core-emission fixture bases. Results match selected `minimal.stdout`
  `039dde3a56e02bbf82ab058ff0e41bba878efce20d2ba0d101f118df5f41eac1`
  and fixture README
  `0c5e588bb3b0320428872a546457536df4483b30250d5937b757a920fd0e63a4`.
- Compared other fixture recipes with their historical commands. The `kernel`
  and `staged` function ASTs used to regenerate the staged JSON fixture match
  historical helper definitions. Generated fixtures retain provenance stating
  that no independently recorded historical hash is available.
- Confirmed explicit mode evidence for `tools/setup-cloud.sh`: historical commit
  output records `create mode 100755`, and the owner recorded `chmod 755`.
  Other exported files use the documented default 0644.
- A read-only Git check earlier in this audit found `/workspace/beryl` clean at
  `0a678b4ae6d41190c4f5a8bf063caba05759d20d`. Later build/test activity belongs
  to the controller's work. This audit made no repository edits; its only
  written artifact is this report.

## Exact continuation checkpoints and unfinished archive

| File | Selected SHA256 |
| --- | --- |
| `axiom/research/source_oracle.py` | `a29677691160c2f9b19fa580f47429760ca647d9ff0d7340d66ea07a35dbcb8f` |
| `axiom/research/tests/test_source_oracle.py` | `8544cec5d9c7e7c10320150b1672cb7e0f62a2e341684d5986abb9387e37a49d` |
| `axiom/research/oracle_receipt.py` | `0a6aba2b43ce10202b3d2b1311345420ae6f7fa2f2aa21bbc94f80d1e3cf43e4` |
| `axiom/research/tests/test_oracle_receipts.py` | `77b22683f5b900dc1f66d0a8e012c1afe0223efa1e98faf7002b7713b629b30b` |
| `axiom/research/protocol/source-oracle-v1.md` | `a4921ae8c22541273c01db2236e6df56731f230b468de5708e6a03af2610e8ec` |

Historical O3 review blockers remain present in the recovered checkpoint. Its
known bugs are intentionally preserved; byte recovery does not approve them.

`recovery-package/unfinished-work.tar.gz` SHA256:
`553165e2aa2855111844c5a85afe235d705a14e17e11c4084f8ebd9b9778b533`.
The archive contains exactly 11 unfinished A1/P1/O3 files plus `MANIFEST.json`.
Every archived file's bytes, size, and digest match the external unfinished-work
manifest; the internal manifest equals that external manifest byte for byte.
Every file has false restoration eligibility, and none of its path/digest pairs
appears in the baseline. For overlapping paths, the baseline keeps the earlier
historical version. The separate O3 regression-test version is
`f4917612d5a2067d73b3dabb30f9f456e4ab30c8d79e65c9d6f94f5360cd5549`.

## Remaining gaps and limits

Five paths in the partial committed-path evidence list remain absent:

- `docs/superpowers/plans/2026-10-16-axiom-oracle-qualification.md`.
- `docs/superpowers/plans/2026-10-16-axiom-scalability/01-core-buffer-and-native-build.md`.
- `docs/superpowers/plans/2026-10-16-axiom-scalability/02-compact-plans-and-checker.md`.
- `docs/superpowers/plans/2026-10-16-axiom-scalability/04-native-measurement-and-experiments.md`.
- `docs/superpowers/plans/2026-10-16-axiom-scalability/05-research-and-publication.md`.

At the final tree audit, `staging/recovery-gaps.json` additionally catalogued
15 paths with unrecovered complete bytes, largely truncated internal reviews,
plans, and original scratch research. The oracle-qualification plan above was
absent from that 15-path list and was separately reported to the controller.
That catalog may be extended without changing the audited baseline tree.
Four ambiguous internal `.superpowers` review/task paths remain withheld.
No runtime module or integration test remains ambiguous in this export.
The evidence lists are partial and do not prove that no other files are missing.

The engine validates supplemental bytes and some evidence fields, but does not
independently prove every supplemental reconstruction step. Its complete-output
substring check still relies on reviewed file identity and completeness
provenance. Single-candidate or chronological selections without an independent
recorded digest remain a lower-confidence class, as the manifest states.

Default regular-file modes, generated fixtures, and earlier verified checkpoints
are intentional recovery choices. Original Git objects, complete cross-thread
chronology, original symlink metadata, and latest-state identity are not recovered
by these checks. Copying or committing this tree should preserve the audited
bytes or identify and validate subsequent changes separately. This report does
not itself verify a later live restore, Git commit, archive upload, or remote push.
