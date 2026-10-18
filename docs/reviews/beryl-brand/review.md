# Public beryl branding

The owner requested the public playground name **beryl** and explicitly requested
removal of the old codename from the current downloadable source. Earlier public
Git history remains; the owner was told that rebranding cannot erase that disclosure.
The public repository was already renamed to `NtEuphoria/beryl-playground`.

The page, accessible names, status messages, example filename, JSON download,
worker, source archive, README, and manifest now use the public brand. The demo
still describes its bounded interpreter scope and does not claim to be Lattice Core.

The exporter creates `beryl-compiler.zip` with a `beryl` namespace. Six expected-once
substitutions update four docstrings and two version identifiers; unexpected
codename occurrences fail export. The private compiler is untouched. Public
semantic/checker labels are `beryl-stencil-i32-v1` and `beryl-checker-v1`.
Public plan digests intentionally differ; cross-brand plans are not interchangeable.

Four package tests pass, including isolated standalone ZIP execution, full manifest
and archive identity checks, unchanged MIT notices, preservation of existing output,
and rejection of unexpected branding markers. Twelve successful comparisons match
private reports except `selected.plan_digest`; four rejection reports and catalogs
match exactly. Real local and static-subpath Chromium checks passed calculation,
selection, download, rejection, keyboard, and responsive behavior.

Independent review approved the exact 19-file artifact and all 11 module ASTs;
only the reviewed docstrings and version identifiers differ from private code.
It also checked browser-worker execution, title/H1/accessibility names, download
filenames, and absence of old-brand requests. One placeholder typo was corrected.
Seven runtime files and both license copies remain unchanged.

Public source commit: `74afafaf611cc2d64d118250d27db874afb82252`.
URL: https://nteuphoria.github.io/beryl-playground/
Live deployment verification is recorded in live-files.json and live-browser.log.
