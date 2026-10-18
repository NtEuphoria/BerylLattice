# Axiom presentation implementation

The presentation build adds real checked-plan execution, independent comparison,
a local playground, and a static browser version of the same Python compiler.
The owner approved the bounded demo under MIT and its19-file release was pushed
to the separate public `NtEuphoria/axiom-playground` repository, commit7a608cb.
The full BerylLattice repository remains private.

The existing finite v1 profile remains unchanged:256 input cells, exact i32,
one two-stage stencil, and three schedules. This work does not claim scalable
loop proof completion, production O3 qualification, a native compiler release,
global optimality, total-memory accounting, or measured speedups.

The [independent final review](2026-10-18-presentation/final-review.md) approved
the integrated path and exact release artifact. It records the resolved Unicode
diagnostic, example-retry status, and standalone source-ZIP license findings.
No review findings remain open.

[Verification](2026-10-18-presentation/verification.json) binds current implementation
hashes to retained evidence. The full product run passed287 tests with22 skips;
final focused runtime/service/HTTP checks passed48 tests; optimized demo checks
passed50. The final packaging-only changes additionally passed normal and
optimized tests. Real Chromium runs exercised the local server and static site
under a repository subpath, all output comparisons, schedule changes, rejection,
downloads, worker timeout recovery, keyboard navigation and four viewport widths.

The public release contains exactly the manifest-listed demo/compiler/runtime
files. MIT notices accompany both the site and the independently downloadable
compiler ZIP; upstream runtime licenses remain separate. The
[release manifest](2026-10-18-presentation/release-manifest.json) lists exact sizes
and hashes. Pinned runtime assets are downloaded with TLS verification and SHA256
checks; no browser request to an external runtime CDN is needed in this release.

GitHub accepted the public source push but rejected Pages creation with403.
The owner enabled `main` at `/(root)` in repository Settings → Pages. The live
site at https://nteuphoria.github.io/axiom-playground/ then passed the actual
Chromium run, schedule change, every-output comparison, exports, rejections,
stale-result, responsive and keyboard checks. Selected served files match the
reviewed bytes and expected MIME types. Exact commit, identities and results are
recorded in `deployment.json`, `live-files.json`, and `live-browser.log.gz` beside
the verification evidence. This live check establishes the deployed demo path.

The separate bounded-source prerequisite is reviewed in PR#2 and does not change
this presentation's v1 path. Its review records170 passing targeted tests in each
Python mode and preserves the original frontend/model bytes and admitted identities.

The subsequent [playground clarity review](playground-polish/review.md) records
the simpler interface, accessibility checks, unchanged compiler/runtime bytes,
and verified public update at commit `83da6e1`.

The public presentation is now branded **beryl** at
https://nteuphoria.github.io/beryl-playground/. The
[branding review](beryl-brand/review.md) records the source-package export,
behavior comparisons, and live verification. Historical public commits retain
the previous name.
