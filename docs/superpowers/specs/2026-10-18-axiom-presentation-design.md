# Axiom presentation build

## Purpose and scope

Provide a working, explainable Axiom demonstration for the user's October 31
presentation target. Axiom is its own experimental declarative language; Lattice
Core is a separate language and a possible native compilation target. The demo
must actually select, check, and execute a plan, then compare every result with
the original-source evaluator. A web interface follows that working path.

The presentation path uses the existing finite v1 profile: one two-stage stencil,
positive H/W with `(H+1)*(W+1) <= 256`, exact i32, input range 0..1023, and the
existing three-schedule portfolio. This is a deliverable alongside the ongoing
compact-loop proof work, not evidence that scalable v2 gates are closed.

## Design decision

A Python standard-library checked runtime plus a local HTTP playground preserves
the existing compiler as the single implementation. Reimplementing Axiom in
JavaScript would create a second semantics; loading a Python browser runtime
would introduce substantial packaging and download dependencies. Native Core
compilation per browser request would depend on unreleased qualification work.
The selected approach runs offline once Python 3.12+ and this checkout exist.

The local server serves only three bundled assets and explicit JSON endpoints.
It launches a bounded worker for each run, never a user-selected command or path.
No public hosting, repository disclosure, or event submission is performed by
this change. Event eligibility and the current program year require verification.

## Checked execution

`axiom.runtime.execute_plan(source_bytes, plan_bytes, data, initial_output,
limits=Limits())` reparses source, admits it, decodes plan bytes, freshly checks
the exact plan, and refuses all ineligible/unknown results before interpretation.
It snapshots exact list/tuple buffers, enforces i32/type/length/disjointness, and
preflights every input before executing operations. It returns an immutable
`ExecutionResult` with unchanged caller buffers, including preserved output on
input-precondition failure. The interpreter is independent of the source
evaluator, validates checked i32 arithmetic, and has no unchecked public entry.

`axiom.playground_service.run_demo(request)` handles a JSON-compatible dict with
exact keys `source` (UTF-8 string), `input_mode` (`ramp`, `zeros`, `checkerboard`,
or `custom`), and optional `inputs` (list, required only for custom). It selects
with existing Limits and 100000 total steps; its initialized output is all -9.
It executes the selected bytes through the fresh runtime boundary and separately
evaluates the original source. Success requires complete observation equality.
No plan bytes, saved success flags, filesystem paths, or commands enter via HTTP.

## API contract

`GET /api/examples` returns `{examples: [{id, title, description, source}]}` with
three complete sources: `balanced` (H5/W7, cap64, multiplication objective),
`no-scratch` (same, cap0), `small-memory` (same, cap64, workspace objective).

`POST /api/run` accepts the run_demo request above, at most 131072 body bytes.
Result fields (all included when selection succeeds):

```
schema_version: 1
status: "success" | "input_precondition_failed" | "no_eligible_plan" | "error"
backend: "checked-plan-interpreter-v1"
source_digest: string
shape: {height: int, width: int, input_height: int, input_width: int}
objective: string
workspace_cap: int | null
selected: {plan_id: string, workspace_bytes: int, multiplication_ops: int,
           plan_digest: string} | null
attempts: [{plan_id: string, eligible: bool, semantic_status: string,
            constraint_status: string, reason: string,
            workspace_bytes: int | null, multiplication_ops: int | null}]
search: {termination_reason: string, work_used: int}
input: [int]
output: [int] | null
comparison: {matches: bool, cells_compared: int} | null
first_bad_index: int | null
diagnostic: {code: string, message: string, offset: int | null} | null
```

An error may return only schema_version/status/diagnostic; clients must not show
old successful output as a current result. A mismatch is an error, never success.
Errors retain stable diagnostic codes and byte offsets without stack traces.
Report downloads are observations for a demo, not O3 qualification receipts.

## HTTP boundary

CLI: `PYTHONPATH=axiom/src python -m axiom.playground --port 8765` from repo root.
Bind only 127.0.0.1; accept only loopback Host with the actual server port and
matching Origin if provided; reject cross-site fetch metadata. Strict JSON,
exact payload validation, body limit, socket timeout, and a 10-second worker
timeout bound work; subprocess invocation uses fixed argv and no shell.
Static routes are allowlisted; no directory or arbitrary-file serving. Disable
CORS, use restrictive CSP and no-sniff headers, do not log submitted source.
This is a local presentation server, not a multi-tenant hosted service.

Use at most16 connection threads to tolerate browser idle/preconnected sockets;
only one compiler worker may run at a time and concurrent runs receive429.

## Playground

An accessible responsive workbench with Axiom branding: restrained forest-green
and warm-neutral colors, strong typography, source editor, three example choices,
input-pattern selector, Run button, status, candidate comparison table, input and
output grids, and downloadable JSON report. Explain the actual supported stencil
and scratch metric beside controls/results. Source text is authoritative; avoid
separate cap/shape controls that can silently disagree with the editor.
Use textContent for dynamic content, no external assets or dependencies.
Loading, errors, unsupported source, rejected inputs, and stale edited results
must be explicit. Keyboard and narrow-screen use are required. No fabricated
speedups, native execution claims, or formal-proof claims.

## Acceptance

For H5/W7 ramp input: cap64 chooses rows2 (48 multiplies,64 scratch bytes); cap0
chooses inline (140 multiplies,0 scratch bytes); all 35 outputs match independently
(first186,last7634). Zero input produces4 everywhere.15x15 remains within profile;
32x32 is rejected. Malformed/unsupported source, invalid custom inputs, altered
plan bytes, ineligible plans, and mismatched observations fail closed. Server
tests cover malformed JSON/length/origin/host/path and real worker execution.
Browser checks cover examples, edits, errors, result download, keyboard use, and
320/768/1024/1440 widths. Full product suite and targeted optimized Python tests
provide regression evidence. Independent review is required before delivery.

## Public-hosting amendment

The user subsequently selected a public hosted link and GitHub Pages if available.
Prepare a static site using a dedicated Web Worker and pinned, vendored Pyodide
runtime to execute the same Python compiler. `transport.js` selects local HTTP
or browser execution through an explicit `data-runtime="browser"` HTML attribute.
There is no alternate JavaScript semantics. Loading/run timeouts terminate and
reset a stuck worker. The static builder includes only the eleven required Axiom
modules, UI assets, and pinned runtime dependencies, with an exact hash manifest.
The build includes no research, recovery, session, Core, or oracle-qualification
material. The precise source payload is reviewable before publication. First
build needs network access to obtain verified pinned runtime files; the built
site serves all assets from its own origin. Test through HTTP in a real browser.

GitHub Pages availability must be established from actual API results. A public
link request does not authorize changing the full private research repository's
visibility. Deployment target creation and release of the concrete bounded demo
must be explicit; prepare all code and artifacts before any required final scope
confirmation. The working local server remains the presentation fallback.

The owner explicitly approved publishing this bounded demo under MIT as
`NtEuphoria/axiom-playground`. Include its scoped license both in the site and
standalone compiler source ZIP. Retain upstream runtime licenses separately.
The existing integration rejected both Pages API access and repository creation;
publication now depends on account access rather than another scope approval.

## Subsequent milestones (research)

Finish and independently review bounded v2 name handling without changing v1;
complete constructive loop certificates and exact work accounting; admit the
scalable checker; qualify updated oracle dependencies and native execution;
then run checked32x32 and2048x2048. These are recorded remaining gates, not demo
acceptance conditions. Preserve private recovery/research material.
