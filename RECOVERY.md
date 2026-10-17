# Project Axiom recovery — 17 October 2026

The available Axiom source, tests, research code, and documentation have been
restored from retained session records. This is a new recovery checkpoint;
the original Git objects and complete original checkout were not recovered.
This report and the `recovery/` archives describe baseline commit `6697e84`.
Subsequent O3 cleanup changes are documented in the
[cleanup follow-up](docs/reviews/axiom-oracle-cleanup-ownership.md).

## What was recovered

- 224 files under BerylLattice, including ignored internal working records,
  and 55 scratch research files were restored to the workspace. Two diagnostic
  files formerly under `/tmp` are preserved only in the baseline archive.
- The pinned Core checkout was restored independently from its Git remote at
  `0a678b4ae6d41190c4f5a8bf063caba05759d20d` and remains clean.
- Eleven unfinished source-name adapter, proof/cost, and oracle regression-test
  files are preserved separately in `recovery/unfinished-work.tar.gz`. They are
  not applied to the active baseline. Earlier versions of overlapping files
  remain in the baseline.
- The uploaded architecture roadmap is included in the combined backup.

Recovery used complete historical additions, exact patch replay, literal
file contents, and independently recorded hashes where available. Some fixtures
were regenerated from complete recorded recipes; these do not have independent
historical byte hashes. Single-candidate files and earlier complete drafts are
labelled in the provenance records. This does not establish an exact restoration
of the last interrupted workspace.

## Fresh verification

| Check | Result |
| --- | --- |
| Product suite in the live restored checkout | 239 tests, OK, 22 skipped |
| Research state, receipts, evaluation, proof feasibility, and oracle receipts | 104 tests passed |
| Research manifest | 24 tests passed |
| Source oracle | 29 tests passed, and 29 passed again under `python -O` |
| Portable cloud setup | Passed |
| Fresh pinned Core native build and capability checks | Passed |
| Pinned Core unit suite | Still fails 2 of 10,814 checks across 583 cases |

The product skips cover optional native/nightly selectors and tests requiring a
lost historical retained toolchain receipt. Fresh native setup creates a new
receipt; it does not recreate that old evidence. The 104-test research run used
a restored snapshot whose corresponding Python files match the live baseline;
it explicitly selected the five suites named above. The manifest and source
oracle checks also passed in the live checkout.

The first product run exposed a missing historical append in an expected-output
fixture. Its exact recorded append was recovered; the affected 13 tests and the
complete product suite subsequently passed. Both logs are retained.

**O3 was blocked at the recovery checkpoint.** That recovered O3 code
had two previously reviewed cleanup-ownership bugs: a forged closed handle
can reach deletion before issuer validation, and child cleanup debt can delete
a reused path after parent cleanup. Passing the recovered tests does not approve
O3 or restore performance/publication claims. The later regression tests are in
the unfinished-work archive; corresponding completed fixes were not recovered.
The follow-up above addresses cleanup; full oracle qualification still requires
real retained execution evidence and approval for the exact implementation.

## Gaps

Original Git history, complete native/generated evidence, scalability plan
chapters 01, 02, 04, and 05, and the complete oracle-qualification plan remain
unavailable. The scalability master README is an earlier complete draft.
Some scratch research and internal reviews are partial; four ambiguous internal
records were withheld. The evidence lists are incomplete and cannot prove that
no additional files are missing.

See `recovery/known-gaps.json` and `recovery/audit-review.md` for details. Read this
recovery report before relying on historical status or completion claims in
restored documents.

## Preserved evidence

- `recovery/restored-files.json`: live restored paths, hashes, and provenance.
- `recovery/baseline-files.tar.gz`: all 281 selected files, including ignored
  internal records and scratch documents, plus the selection manifest. Paths
  are relative to a staging root; extract into a new directory for inspection.
- `recovery/history-evidence.tar.gz`: retained session records, reconstruction
  tools, candidate bytes, and an internal per-file integrity manifest.
- `recovery/unfinished-work.tar.gz` and its external manifest: isolated WIP.
- `recovery/validation/` and `recovery/verification.json`: fresh test logs,
  setup evidence, artifact hashes, and verification scope.

The independently audited selection manifest SHA256 is
`2cb5f707d7b9f43cf2acdb09f2ed3af0f00f01e596ba5fc2c05290004d042882`.
The recovery evidence may contain confidential project context; preserve it in
private storage. The checkpoint and combined backup are local until explicitly
saved outside this cloud environment. Their existence alone does not establish
remote persistence.

## Resume work

Python 3.12 or newer is required. From the repository root:

```sh
bash tools/setup-cloud.sh
cd axiom
PYTHONPATH=src python -m unittest discover -s tests -v
```

For a new native qualification, keep Core at the exact pin above and run from
the repository root:

```sh
bash tools/setup-cloud.sh --native --core ../beryl --prefix ../axiom-native
```

Automatic native bootstrap targets Debian 13 amd64. The setup script documents
the verified explicit-Clang alternative. It reports the pinned Core unit
failures separately from successful build/capability checks.

The combined backup contains Git bundles for both repositories and separate
restoration instructions. Restore into new directories and verify those bundles
before replacing any existing checkout. Resume engineering with the recorded O3
blockers and a review of the isolated unfinished work.
