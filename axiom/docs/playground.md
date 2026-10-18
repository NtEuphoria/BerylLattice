# Axiom playground

This is a working demonstration of Axiom's bounded declarative language: write a
computation and scratch constraint, let Axiom select and check a schedule, then
execute that schedule and compare every result with the independent source
evaluator. Lattice Core is a separate language. This demo uses Axiom's checked
Python plan interpreter; it does not require or claim native Core execution.

## Start

Install Python 3.12 or newer. From the repository root:

```sh
python3 tools/run-playground.py
```

On Windows, use `py -3.12 tools/run-playground.py`. The server prints its local
browser address. Leave the terminal running, open that address in your own
browser, and press Ctrl+C in the terminal to stop. If port8765 is occupied:

```sh
python3 tools/run-playground.py --port 8766
```

There is no npm/pip install and no CDN or external font. The playground works
offline after obtaining Python and the source. It binds to the local computer
only. This server is not a public hosting service; a hosted deployment needs a
separate deployment design and a decision about source disclosure.

## Build the public static site

From the repository root:

```sh
python3 tools/build-playground-site.py --output /tmp/axiom-playground-site
```

Choose a new/empty output directory. The builder downloads pinned, SHA-256-checked
Pyodide0.27.7/Python3.12.7 runtime files over verified HTTPS. It bundles the same
eleven Python modules used by the demo, runtime license texts, and an exact
release manifest. The output is about14MB and contains no Core, research,
recovery records, or Git history. It still discloses the bounded Axiom compiler
source, available through the playground's Demo source link.

The built site needs only static HTTP/HTTPS hosting. The entire computation runs
in a Web Worker in the visitor's browser; source and input data stay there. All
runtime files are served from the site's own origin. Relative URLs support a
GitHub Pages repository subpath. Opening the HTML as a local file is unsupported;
use an HTTP server to test the built directory. This browser version makes the
same finite-profile claims as the local server version.

`release-manifest.json` lists each file's hash and every Python archive member.
The owner approved the bounded demo under MIT on October18,2026; its scoped
license is included in the site and compiler source download. Upstream browser
runtime licenses remain separate. The builder does not create a repository or
publish a site. This grant does not cover private research/recovery material.
The generated README explains hosting MIME types and CSP. GitHub Pages ignores
`_headers`; the page also contains its own CSP meta policy.

The owner created the public repository and the approved release was pushed to
`NtEuphoria/axiom-playground` (`main`, commit7a608cb). The current GitHub connection
returned403 when enabling Pages. In Settings → Pages, publish the `main` branch's
root directory. Repository push access does not establish Pages configuration
permission. Live deployment status is recorded in the presentation review.

## A two-minute presentation

1. Start with the balanced example and ramp input. Explain: the source declares
   a two-stage array computation and a64-byte plan scratch constraint, but does
   not specify the schedule. Press Run.
2. Show the selected two-row schedule:48 multiplication operations and64 bytes
   of plan scratch. All35 output cells agree with the independent evaluator.
3. Choose the zero-scratch example and run again. Axiom chooses inline execution:
   140 multiplications, zero plan scratch, and the same output.
4. Choose the small-memory objective. Explain that the preferred resource can
   change the selected schedule. These are comparisons within three candidates.
5. Edit a source dimension or input pattern and run again to show real execution.
   Try zeros: every output becomes4. Download the current report for a record.

If showing errors, use an unsupported computation or custom input containing1024.
The program must report rejection instead of presenting an old success as current.

## Exactly what works

The current profile accepts one two-stage stencil: square each input plus one,
then add four neighboring producer values in the source's prescribed grouping.
Names, positive H/W shapes, comments, scratch cap, and objective may change.
The maximum input is256 cells: `(H+1)*(W+1) <= 256`. A15×15 output fits;32×32 does
not. Input values are exact integers0..1023; arithmetic is checked i32.

All three candidate schedules are checked against source. The chosen plan is
checked again at the execution boundary; saved success flags grant no authority.
Execution and the source evaluator operate independently and their complete
observations must agree. The browser is a client of the real Python compiler,
not a canned animation or a second JavaScript language implementation.

Plan scratch is the plan's logical scratch arena. It excludes input/output,
SSA temporaries, Python memory and backend overhead. Multiplications are counted
operations, not measured speed. The interpreter may store scratch sparsely; its
Python allocation is not the displayed logical arena. The selected schedule is
best among the checked candidates under the ranking, not globally optimal.

Downloaded JSON records are demo observations, not signed certificates or O3
qualification receipts. This prototype is not a general-purpose language release,
a formal proof of the full implementation, or completion of compact-loop research.

## Troubleshooting

- A Python version error means the selected executable is older than3.12.
- An occupied port can be resolved by selecting a different `--port`.
- If a run times out, reduce source complexity and retry. The local worker has
  a10-second deadline; a timed-out run does not establish program infeasibility.
- Unsupported source is expected outside the documented profile. Change the
  sample dimensions/constraints while retaining its equation structure.
- The server deliberately rejects foreign origins and arbitrary file paths.
  Use the printed address directly instead of embedding it in another website.
- Stop and restart with the documented command after restoring an environment;
  a saved filesystem does not preserve a live server.

## Validation

From `axiom/`:

```sh
PYTHONPATH=src python3 -m unittest tests.test_runtime tests.test_playground_service tests.test_playground_http -v
PYTHONPATH=src python3 -O -m unittest tests.test_runtime tests.test_playground_service tests.test_playground_http -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The full suite includes separately gated native tests. Skips are not native
qualification. See the retained presentation review for the actual current run.

Optional browser verification uses Playwright and Chromium installed separately
as developer tools, not runtime dependencies:

```sh
node tools/check-playground-browser.cjs http://YOUR_TEST_SERVER
```

Run that command from the repository root. `PLAYWRIGHT_MODULE` can select an
existing Playwright installation and `CHROMIUM_PATH` an existing browser binary.
It exercises actual execution, output equality, schedule changes, downloads,
rejections, stale-result clearing, narrow screens, and keyboard navigation.
