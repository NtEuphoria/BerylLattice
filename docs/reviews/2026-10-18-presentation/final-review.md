# Final Axiom presentation integration review

Reviewed 2026-10-18. **SPEC PASS / QUALITY APPROVED for the bounded presentation implementation and the exact static artifact identified below. No outstanding findings.** This review does not establish public deployment, native conformance, scalable proof completion, or O3 qualification.

## Scope and method

Read the presentation design and implementation plan, the combined `final-review.diff`, the actual final runtime/service/HTTP/UI/worker/builder sources, relevant existing selection and source-evaluator contracts, the new tests and documentation, and all three independent component reviews. The supplied diff SHA-256 is `049af83f7ac140628a0bc6f20f8a66abead5f4216e2a3895d270741d31be4eab`. Subsequent scoped MIT licensing, archive metadata, documentation, and `.nojekyll` changes were reviewed directly in the current files and built artifact.

The review concentrated on integration defects and truthful presentation claims. It did not repeat the broad product suite or browser suite. Independent execution consisted of in-memory archive reproducibility/source/license checks and complete final artifact manifest verification. No product files were changed by this reviewer.

## Integrated behavior

- Source is authoritative for dimensions, input interval, scratch cap, and objective. The service parses and admits the submitted bytes and calls the existing finite portfolio selector with the stated budget. The selected artifact bytes cross the execution boundary; a stored selection/check result is not execution authority.
- `execute_plan` independently reparses source, decodes those exact plan bytes, and freshly checks eligibility before interpretation. Its private input/output snapshots enforce exact scalar types, i32 bounds, extents, and caller disjointness. Complete input preflight precedes any physical operation. Failed preconditions preserve the initialized output and caller buffers.
- The interpreter walks checked physical operations. The original-source evaluator walks retained source equations separately. Service success requires equality of the complete immutable observations, including every output, observed input, status, and first failure position. A disagreement yields an error without successful output. Neither HTTP nor browser mode supplies an alternate JavaScript implementation or a canned successful result.
- Local HTTP invokes a fixed Python worker with a controlled package path/cwd, bounded body and time limits, loopback Host/Origin checks, explicit static routes, bounded connections, and one compiler worker. Browser mode calls the same packaged service in a dedicated Pyodide worker with reset-on-timeout behavior and strict request decoding. Relative URLs preserve repository-subpath operation.
- UI edits clear the accepted report, matrices, candidates, and download state immediately; generation checks prevent late old responses from becoming current. Input rejection, source/transport errors, no eligible plan, and independently matching execution are distinct. The earlier example-retry status inconsistency is resolved. Dynamic values use text content and the documented keyboard/narrow-layout paths have retained browser evidence.
- Documentation and visible copy preserve the finite v1 bound, three-candidate ranking, checked interpretation, Axiom/Core separation, logical scratch versus actual memory, and operation count versus speed. Reports are observations, not qualification receipts or authoritative attestations. The static source-disclosure boundary is explicit and does not include the private repository/history, Core, recovery/session records, or scalable qualification artifacts.

## Resolved integration finding

The initial MIT amendment emitted a site-root LICENSE but left the independently downloadable `axiom-compiler.zip` without its notice. This was raised during this review and corrected before approval. The final archive contains the eleven allowlisted Python modules plus its own root LICENSE. The manifest retains eleven `compiler_modules` identities and records all twelve members separately in `compiler_archive_members`. The archive and site notices exactly match the approved `axiom/playground-LICENSE`. The release README describes the bounded license scope and keeps third-party runtime licensing separate. Focused normal and optimized packaging regressions passed after the correction.

The earlier component-review Unicode diagnostic and example-retry findings are also resolved; their scoped rechecks are recorded in `runtime-review.md` and `web-review.md`. No parked findings remain.

## Exact final artifact

Reviewed final directory: `/workspace/scratch/axiom-presentation-2026-10-18/axiom-playground-pages`. Independently confirmed every file is byte-identical to the already reviewed `axiom-playground-public` directory.

- Release manifest SHA-256: `bdf1bd7bd5678a9f33f643f1a46deb1812381a9f72ca01a9a44f90a50f5f131c`.
- Compiler ZIP SHA-256: `abd6d1a35979e7f3901d5dd2a25c4988540b0e055d4db9e4d7310a296efb1ffe`.
- Complete site ZIP SHA-256: `3591bc0bf259d51d2e0c55f319750e323192739c6dfa28b293311220201577f4`.
- Exactly 19 files including the manifest; every other emitted file is enumerated with a correct size and SHA-256. The final empty `.nojekyll` is the sole release-file change from the previously checked MIT artifact; all other file bytes are identical.
- All twelve archive members match their recorded sizes/hashes. All eleven Python module bytes match the current source. The unchanged JavaScript/CSS assets match current source. The vendor configuration uses `./runtime/`; pinned runtime hashes and licensing were additionally assessed by the prior independent static review.
- Repeated archive construction in memory produced identical bytes in the current toolchain. This is not a reproducibility claim across arbitrary Python/zlib/OS versions.

Reviewed implementation SHA-256 identities:

| File | SHA-256 |
| --- | --- |
| `axiom/src/axiom/runtime.py` | `54d35cd52e4ad19944ea4f0807ccadac7ef999a0c635e4776cd2ea111308b71b` |
| `axiom/src/axiom/playground_service.py` | `562dc076bd787641804af4cab8a7b8b691bb7f51d5fbed2d33751118d654eb23` |
| `axiom/src/axiom/playground.py` | `e70675ae47f1859b711a034b831afa7083e4dfacb94fcb3c972172bfa974af39` |
| `tools/build-playground-site.py` | `f69dcfaf6c0faf44bf2cd73fc4e8dd03be97769d6e06ea89d797a257474549bf` |

## Validation evidence and limits

Retained parent/implementer logs were inspected without representing them as fresh reviewer executions:

- Product suite: **287 tests, OK, 22 skipped**, in `product-tests.log`. Skips concern explicitly gated native/toolchain/qualification paths and establish no native conformance.
- Final normal runtime/service/HTTP checks: **48 passed**, in `final-runtime-http-tests.log`.
- Optimized demo checks: **50 passed**, in `optimized-demo-tests.log`, before the packaging-only licensing amendment; the changed packaging tests subsequently passed normally and under `-O`.
- Real Chromium/local-HTTP and static repository-subpath evidence covers actual checked execution, schedule changes, complete outputs, report download, input/source rejection, stale-result clearing, four viewport widths, keyboard navigation, and no page errors. The final MIT artifact also passed the retained full UI browser check. `.nojekyll` changes host processing metadata only and preserves those tested application/runtime bytes.
- Component reviews separately checked adversarial plan bytes, unknown/ineligible plans, maximum admitted shapes, mismatch injection, HTTP framing/origin/time/concurrency controls, worker timeout recovery, complete release enumeration, and same-origin runtime requests.

Python/Linux and Chromium execution have actual evidence. Windows launcher portability is supported by the implementation's platform-neutral paths/subprocess calls and documented command, but was not executed on Windows here. Safari, Firefox, physical mobile devices, and a full accessibility audit are not established by Chromium viewport checks.

The owner has explicitly approved the separate bounded MIT release and created the public target repository. That authorization is separate from this technical review. Public push/Pages enablement, served MIME/CSP behavior, and a post-deployment browser run remain root-owned actions; this report claims none of them complete. The known earlier Pages API denial does not invalidate the working local server or reviewed static package.
