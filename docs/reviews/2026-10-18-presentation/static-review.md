# Static playground packaging and browser-runtime review

Reviewed 2026-10-18. **Spec verdict: pass for the prepared default vendored release. Quality verdict: approve within this review scope; no blocking or nonblocking defect was confirmed.** No deployment or publication approval is implied.

## Scope and artifact identity

Read-only independent review of `tools/build-playground-site.py`, `axiom/src/axiom/playground_web/transport.js`, `axiom/src/axiom/playground_web/worker.js`, and `axiom/tests/test_playground_site.py` against the design spec's Public-hosting amendment. The task's abbreviated `tests/test_playground_site.py` resolves to `axiom/tests/test_playground_site.py` in this repository. UI presentation and the already reviewed checker/runtime algorithms were outside this review; their integration and source packaging were inspected.

- Review diff: `/workspace/scratch/axiom-presentation-2026-10-18/static-review.diff`, SHA-256 `d81295211db26b7309b6d5551ddab703f87af1443ae27483cbc718ccbf29c91e`.
- All four current files matched the exact added-file contents of that diff during review.
- Checked artifact: `/workspace/scratch/axiom-presentation-2026-10-18/static-site-reviewed`.
- Release manifest SHA-256: `9dcdd949d1749caff93f4eb5759b9b7372e6f28ee58777abff9ce3a0d56e8764`.
- Compiler ZIP SHA-256: `72ab4e7a912fa996fe8686b4e08c9f79fee7c03b093e545a1d2c628b8b3569e8`.

## Findings

No concrete severity-rated defects found. No research source, Core source, recovery material, session material, private evidence, or oracle-qualification artifacts were present in the reviewed release payload. This conclusion concerns the explicitly enumerated release, not the full private checkout or a future deployment.

## Spec and implementation assessment

| Requirement | Evidence and assessment |
| --- | --- |
| Exact source disclosure boundary | `build-playground-site.py:19` defines eleven literal module names; `:53` creates ZIP members from those names without directory recursion. Independently enumerated the artifact ZIP and verified each member byte-for-byte against the corresponding source. Its complete import graph stays within these modules and the Python standard library. |
| Exact release contents and hashes | `build-playground-site.py:21` allowlists five UI/runtime assets. Runtime dependencies, generated configuration, headers, README, ZIP, and manifest are added explicitly. Independently checked the manifest against every emitted file: sixteen manifested files plus the manifest itself, no extras, with all byte lengths and SHA-256 values matching. Compiler member hashes also matched. |
| Real Python semantics | `worker.js:18` imports `get_examples` and `run_demo` from the packaged service. The run path calls that function directly. The packaged service selects a plan, freshly checks/interprets it, separately evaluates the original source, and compares the complete observations. No JavaScript substitute, canned output table, or successful-result fixture is involved. |
| No submitted-code interpolation | `worker.js:44` binds the request as a Python string through `python.globals.set`; the executed Python expression is fixed code and strict JSON decoding supplies the service input. The bound global is deleted in `finally`. Submitted source reaches the Axiom parser as data. Both transport and worker enforce 131072 UTF-8 request bytes. |
| Pinned runtime and licenses | `build-playground-site.py:23` pins five runtime assets and two license texts by versioned HTTPS URL and SHA-256. Cache hits receive the same hash check as downloaded bytes (`:40`). Default mode is vendor. Independently checked all seven artifact hashes against the pins and read lock metadata confirming Pyodide 0.27.7, CPython 3.12.7, wasm32/Emscripten 3.1.58. Included license texts and versioned upstream source links identify Pyodide/MPL-2.0 and Python. This verifies the implemented license packaging, not a separate legal opinion or an Axiom license grant. |
| Root and repository-subpath hosting | HTML and module assets use relative paths. Worker creation resolves against `import.meta.url`; runtime configuration, compiler archive, and runtime assets resolve against the worker URL. The retained real Chromium run used `/static-site-reviewed/` and requested every application/runtime asset from that same subpath and origin. |
| Worker loading/error/timeout/retry lifecycle | `transport.js:11` terminates the current worker, clears the boot promise, clears timers, and rejects pending requests. Boot errors and worker errors invoke that reset. Boot has 60 seconds; computation has 15 seconds. Responses from an obsolete worker are ignored by instance identity. A pending computation blocks a second one; the worker also has a busy guard. A failed boot cannot leave its partially initialized Python object reusable because the parent terminates that worker. The retained injected-timeout browser test demonstrates a fresh worker and a successful real-Python retry. |
| Reproducibility and safe local build | All inputs are gathered and verified before output is written. Nonempty output directories are refused. ZIP order, timestamps, permissions, and manifest serialization are fixed. Independently generated the archive twice in memory; both byte sequences matched the checked release ZIP. This establishes reproducibility in the current toolchain, not across arbitrary Python/zlib/OS versions. The builder performs no Git changes or publication. |

## Validation evidence and limits

Independent checks in this review were artifact enumeration, complete manifest verification, exact source/diff identity checks, dependency inspection, runtime pin/metadata inspection, and repeat archive-byte comparison. No repository files were changed and no broad test suite was rerun.

Inspected retained implementer execution evidence, without representing those runs as fresh independent executions:

- `static-green.log`: both static-site tests passed, including isolated Python execution directly from the built ZIP, exact archive allowlisting, manifest checks, and nonempty-output preservation.
- `static-browser.log` and `static-browser-csp.log`: three real Chromium examples select rows2/inline/inline, produce all 35 matching outputs (186 through 7634), and reject malformed source. The CSP run adds restrictive worker response headers. Recorded page errors are empty and recorded asset requests are same-origin.
- `static-timeout-check.cjs` and `static-timeout.log`: suppresses the first worker's run response, advances the browser clock, observes the timeout, and then confirms a second worker executes the original Python request successfully.

The committed static-site tests currently exercise CDN-mode packaging; the retained real-browser and independent artifact checks supply the vendor-runtime evidence. CDN mode is explicitly documented as trusting the external runtime host and is not the default release reviewed for publication. The generated `_headers` file applies only on hosts that honor it; the README correctly notes that GitHub Pages ignores it and requires separate handling of unsupported response headers. No actual public host, GitHub Pages availability, deployment settings, or post-deployment behavior was assessed here.
