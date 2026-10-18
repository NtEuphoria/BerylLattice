# Axiom playground UI implementation

Implemented only the assigned `index.html`, `app.js`, and `style.css` assets under
`axiom/src/axiom/playground_web`. No commits made.

Read the accepted presentation design and implementation plan and applied the
`engineering-suite-motion-design:frontend-ui-engineering` skill. Used warm-white
surfaces, forest-green source and result accents, system sans/mono type, and a
serif title to create a compiler workbench. There are no external assets, fonts,
CDNs, dependencies, inline scripts, or dynamic HTML insertion.

## Implemented interactions

- Editable labelled Axiom source, three API-loaded example buttons and descriptions.
- Input patterns and labelled custom JSON input; helpful parse errors focus the field.
- Run action and Ctrl/Cmd+Enter shortcut, startup/loading and runtime-aware messages.
- Freshness guard: edits immediately clear all displayed result data and disable export;
  pending asynchronous completions cannot repopulate stale results.
- Async requests use generation identity, cancellation guards and a15-second UI timeout.
- Status differentiates verified execution, no eligible plan, precondition failure,
  and source/transport errors. A success payload must contain complete matching
  output comparison before displaying successful execution.
- Candidate schedule table with eligibility/rejection reasons, selected scratch,
  multiplication count, shape, and a complete row/column-labelled output matrix.
- Inspectable input matrix and source/plan/search details; current result JSON export.
- Scratch/count scope disclosure, v1 profile limits, interpreted execution, and
  Axiom/Core distinction remain visible. Report is labelled an observation, not an
  O3 qualification receipt.
- Transport is delegated to `transport.js` via async `getExamples()`/`runDemo()`.
  Modules, CSS and home links are relative for repository-subpath deployment.

## Verification performed

- `node --input-type=module --check < axiom/src/axiom/playground_web/app.js`: pass.
- `git diff --check`: pass at time of handoff.
- Chromium/Playwright rendered smoke test with a deliberately mocked transport:
  `/workspace/scratch/axiom-presentation-2026-10-18/ui-smoke.cjs`.
- All320/768/1024/1440 viewport widths had document/body widths equal to viewport;
  tables and source scroll internally. Results in `ui-smoke.json`.
- Checked35 rendered output cells, stale edit clearing, disabled export after edit,
  custom JSON rejection/focus, and late response suppression. No page JavaScript errors.
- Inspected screenshots at1440 and320; corrected offscreen skip-link rendering and
  substituted a CSS arrow for a missing system-font glyph.
- Screenshots `ui-{320,768,1024,1440}.png` are MOCK-TRANSPORT DESIGN CHECKS and must
  not be presented as execution evidence.
- Markup uses native buttons/select/textarea/details, explicit labels, table headers
  and captions, a polite atomic status region, focus-visible outlines, and a skip
  link. Reduced-motion mode disables animation. Axe-core was not installed, so
  automated accessibility conformance is not claimed.

## Handoff

Root/transport agents are running actual local/browser execution checks. The above
mock smoke checks establish UI behavior only. The real service and Python/WASM
execution require their separate integration verification. Transport and worker
files belong to another agent and were not edited here.

## Independent-review follow-up

The independent reviewer reproduced a state bug: retrying example loading after
manually completing a run changed the global status while leaving the result and
export active. `ui-example-retry.cjs` reproduces this with a mocked transport;
both retry success and retry failure failed before the fix (process exit1).
`loadExamples` now confines retry messages to the example picker whenever source
or a current result exists. It also preserves an active computation's busy state.
Both original cases and retry-during-run pass after the fix (exit0), with evidence
in `ui-example-retry-red.json` and `ui-example-retry-green.json`. General responsive,
stale-edit/race, custom JSON, syntax and diff checks passed again.

The public browser runtime also now shows relative `Demo source` and `Release
notes` footer links for the static package's compiler ZIP and README. Both remain
hidden in local-server mode, where those paths are intentionally unavailable.
