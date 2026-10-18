# Axiom local HTTP and UI independent review

Final verdict: approved, with no outstanding findings in the reviewed local-server and UI scope. The initially reported nonblocking P3 was corrected and verified in the follow-up below.

## Scope and artifact identity

Reviewed the complete supplied `web-review.diff` (SHA-256 `0d2e544ba08d402ba4bdfcee4ff0e07392ba3393a6b3939a51f9eeaa03ad98cf`) against the presentation design and implementation plan. Scope: `playground.py`, `test_playground_http.py`, and `playground_web/{index.html,app.js,style.css}`.

Also reviewed the subsequent complete local HTTP concurrency delta and UI constraint-rejection wording delta. Final reviewed Git blob hashes:

- `playground.py`: `8011207f38338b8340de10b91629d53f4f39d301`
- `test_playground_http.py`: `e61fdb3bfee813bcaa0364fc4b8937619c0e9ba5`
- `index.html`: `1594a5c093c8acd089ae13b25cc9ea9a21a0e20b`
- `app.js`: `9d7353214b2b84402e9f700a3e0f7f7b981a3d85`
- `style.css`: `62968da8726e7760ed24c6fdc9895f2d9fd96baf`

Transport, browser worker, static builder, runtime/service semantic correctness, deployment, and publication are separate review tasks. Their absence from the initial artifact is not a finding here. Read service and transport contracts only to check integration assumptions.

## Initial finding (resolved)

### P3 / UI-EXAMPLES-STATUS: retrying examples overwrites the current run status

Location: `axiom/src/axiom/playground_web/app.js:261`, `:278`, and `:282` (`loadExamples`).

If initial examples loading fails, users can enter source manually and run successfully, as the error copy explicitly allows. Clicking “Retry loading examples” afterward sets the shared execution status to loading and then “Ready when you are,” while the successful output stays visible and Export JSON remains enabled. A retry failure similarly replaces the execution status with an examples error. This makes the run status disagree with the displayed result. The same retry control remains available while a manually entered run is in progress.

Targeted reproduction used real Chromium with a controlled mock transport: first `getExamples()` rejects, `runDemo()` returns a complete successful result, and the second `getExamples()` resolves. Observed:

```json
{
  "beforeRetry": "Execution checked. Every output matches.",
  "afterRetry": "Ready when you are",
  "outputVisible": true,
  "exportEnabled": true
}
```

Suggested correction: keep example-loading feedback in the examples area, or preserve the shared execution status while a current report or active run exists. Do not clear a valid report merely because examples are retried. Verify both successful and failed retries after a manual run, and retry while a run is pending.

Severity rationale: the computed result stays current and accurate, and edited inputs still clear it. This is a status-consistency issue on the recovery path, not stale output acceptance or a boundary bypass.

## Spec and quality assessment

- HTTP binds only `127.0.0.1`, checks a single actual-port loopback Host and matching supplied Origin, rejects cross-site metadata, and provides no CORS allowance.
- The server exposes fixed routes/assets, validates exact payload keys and strict UTF-8 JSON, rejects ambiguous body framing, applies body/read/worker limits, and uses fixed worker argv/cwd/PYTHONPATH without shell interpolation. Submitted source and paths do not enter request logs.
- The final concurrency delta removes serial blocking by idle browser sockets while bounding connection threads to 16 and compiler workers to one. Semaphore and worker-lock release paths are balanced. Overlapping computations receive a stable 429 response.
- UI edits immediately clear output, candidate data, and downloadable reports. Generation checks prevent older pending responses from repopulating results. Success requires complete output comparison. Precondition rejection, unsupported source, and transport errors remain distinct from successful execution.
- Dynamic content uses `textContent`; no external UI assets or HTML injection sink was introduced. Controls have native keyboard behavior, explicit labels, visible focus, status semantics, and scrollable labeled matrices. CSS supports narrow viewports and reduced motion.
- Scratch versus total memory, operation count versus speed, interpreted execution, v1 limits, Axiom/Core distinction, and non-qualification report scope are accurately disclosed.

## Evidence and limits

- Inspected `ui-report.md`, `ui-smoke.json`, and the 320px screenshot. The supplied UI smoke exercises 320/768/1024/1440 widths, 35 output cells, stale-edit clearing, custom-input error focus, and late-response suppression. Its mocked transport is explicitly not compiler execution evidence.
- Inspected final `http-green.log` and `http-optimized.log`: each reports 23 tests passed. Read their tests, including actual subprocess execution, strict protocol rejection, import-shadow resistance, CLI startup/shutdown, idle-browser progress, and one-worker concurrency.
- Parent reports a separate actual Chromium/local-server run passed schedule changes, outputs, report download, rejections, mobile layout, and keyboard interaction. This review does not claim to have independently repeated that broad run.
- Independently ran only the targeted Chromium reproduction above. No broad suite rerun and no product source changes were made by this reviewer.
- This is a focused implementation review, not a full accessibility audit or public-hosting security assessment.

## Follow-up: P3 resolved and final browser-only links reviewed

Reviewed the final UI delta against the original artifact and the previously reviewed constraint-rejection wording. Final UI Git blob hashes:

- `app.js`: `b2f132c247706c7d25ce86547de165e8c41482ad`
- `index.html`: `60247668185554e399b5a581eb315b3d16b06886`
- `style.css`: `f01df142e40aa8d404425078588a9ef02d58bce6`

`loadExamples()` now confines picker loading/error messages to the examples area when source, a current report, or an active run exists. Initialization-only execution-status changes are also protected by the request generation. It preserves `Boolean(activeController)` when updating the busy state, so retrying examples no longer makes an ongoing computation appear idle. Current output and export remain available after both successful and failed retries. UI-EXAMPLES-STATUS is resolved.

Read the implementer's `ui-example-retry-red.json`, `ui-example-retry-green.json`, and regression script. Independently repeated the script's three Chromium cases against the final source assets: successful retry after a run, failed retry after a run, and retry during a pending run all passed. Local release links were hidden. The script's original localhost server had stopped (`ERR_CONNECTION_REFUSED`), so the independent run served the same final assets through Playwright route fulfillment while retaining the existing controlled mock transport; no HTTP-suite rerun or product change was needed.

The added release navigation uses fixed relative links to `./axiom-compiler.zip` and `./README.md`, a labeled native navigation element, and a download attribute for the source archive. It remains hidden by default and is exposed only by explicit browser runtime mode. The CSS retains the global `[hidden]` rule and narrow-screen footer layout. No new finding in this small delta. Archive contents and static deployment integrity remain in the separate static-site review scope.
