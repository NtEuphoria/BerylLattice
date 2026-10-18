# Axiom Presentation Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans. Follow test-first implementation and independent review.

**Goal:** Deliver a real checked Axiom execution path and an offline-capable local web playground for the October31 presentation target.

**Architecture:** Keep the existing v1 compiler as authority. A fresh checked runtime executes selected plan bytes, and a separate original-source evaluator compares all results. A bounded local HTTP worker exposes this path to bundled static assets.

**Tech Stack:** Python3.12+ standard library; HTML/CSS/JavaScript without runtime dependencies.

**Spec:** [Presentation design](../../specs/2026-10-18-axiom-presentation-design.md)

## Global constraints

- Preserve v1 language/profile limits and source/checker identities.
- No shell execution of submitted source, shell interpolation, arbitrary paths, or disclosure of private research. A pinned vendored browser runtime supports the user's subsequently requested public static site.
- Every executed plan is freshly checked from exact source and plan bytes.
- Compare every output with the independent original-source evaluator.
- Plan scratch is not total memory; operation count is not measured speed.
- Axiom and Core remain separate languages; demo execution is interpreted.
- Keep O3 and scalable v2 qualification status explicit; no synthetic approval.

## Review focus

- Invalid source and editing after a run must not leave a misleading successful result.
- Input precondition/type/length failures must preserve caller buffers.
- Untrusted plan bytes and injected mismatches must never result in success.
- HTTP origin/path/body/time controls must bound and isolate local requests.
- The complete demo must work without CDN assets or Core installation.

## Task1: Working checked runtime and demo service

- [x] Add failing behavioral tests in `axiom/tests/test_runtime.py` and `test_playground_service.py`.
- [x] Implement `axiom/src/axiom/runtime.py` and `playground_service.py` with the spec's API.
- [x] Verify all schedules, adversarial byte mutation, precondition handling, source errors, maximum shape, and full comparison.
- [x] Independently review the runtime/service diff and resolve material findings.

## Task2: Local web playground

- [x] Implement `axiom/src/axiom/playground.py` and `playground_web/{index.html,app.js,style.css}`.
- [x] Add `axiom/tests/test_playground_http.py` before the HTTP implementation.
- [x] Run real HTTP/worker tests, browser interaction, narrow-screen and accessibility checks.
- [x] Independently review the HTTP/UI diff and resolve material findings.

## Task3: Presentation and reproducibility

- [x] Document exact startup, supported scope, a two-minute walkthrough, troubleshooting, and honest claims in `axiom/docs/playground.md`.
- [x] Add a CLI demo/smoke path and tested packaging/start instructions; update README.
- [x] Run product suite and relevant optimized tests; retain current evidence and independent review.
- [x] Commit/push a reviewable private branch and draft PR; publish only the explicitly authorized bounded MIT release. Registration remains the owner’s action.

## Task4: Public-hosting preparation (user amendment)

- [x] Add `transport.js` and `worker.js` to run the same Python service via pinned Pyodide when browser mode is explicitly selected.
- [x] Add an allowlisted static-site builder with exact inclusion/hash manifest and runtime licensing.
- [x] Test actual built artifact in Chromium, including alternate schedules, errors, and hosted subpaths.
- [x] Check GitHub Pages capability; complete reviewable package before any source-disclosure or external-action blocker is handed to the user.

## Parallel proof prerequisite

Bounded v2 source-name recovery is implemented and reviewed on a separate branch
from the same O3-fix base. It does not change this demo's v1 implementation and
must retain its own qualification/dependency regression evidence. Full P1/F1
proof construction remains a separately reported research gate.

## Progress

Initial design uses the user's explicit request to build the working copy and
playground as authorization to proceed. Existing recovery checkout and O3 worktree
are reused; no new worktree or public deployment is created.

## Deployment follow-through

- [ ] Verify GitHub Pages after the owner enables main/root; API creation returned403.

The owner approved MIT publication and created the separate public repository.
The exact19-file release is pushed as7a608cb. Independent final review approved
all code and the release manifest; no private research was included.
