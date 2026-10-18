# Axiom playground

Try the [live playground](https://nteuphoria.github.io/beryl-playground/).
The approved MIT demo source is in
[NtEuphoria/beryl-playground](https://github.com/NtEuphoria/beryl-playground).

The public presentation is branded **beryl**. Its compiler is the bounded Axiom
demo; it is not Lattice Core. Earlier public Git commits retain the old codename.

This is a working demonstration of Axiom's bounded declarative language: write a
computation and scratch constraint, let Axiom select and check a schedule, then
execute that schedule and compare every result with the independent source
evaluator. Lattice Core is a separate language. The browser compiles Axiom's
checked finite plan to WebAssembly; the local server retains the Python plan
interpreter. Neither requires or claims native Core execution.

## Start

Install Python 3.12 or newer. From the repository root:

```sh
python3 tools/run-playground.py
```

On Windows, use `py -3.12 tools/run-playground.py`. The server prints its local
browser address. Leave the terminal running, open that address in your own
browser, and press Ctrl+C in the terminal to stop. Windows also supports
Ctrl+Break for a clean shutdown; the subprocess test uses that event with an
isolated process group. If port8765 is occupied:

```sh
python3 tools/run-playground.py --port 8766
```

Or use `--port 0` to choose an available port automatically, then open the
address printed by the server. Starting a second server on an occupied port
reports an error and leaves the existing server running.

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
thirteen Python modules used by the demo, runtime license texts, and an exact
release manifest. The output is about14MB and contains no Core, research,
recovery records, or Git history. It still discloses the bounded Axiom compiler
source, available through the playground's Demo source link.

The public source archive is `beryl-compiler.zip`, with the Python package named
`beryl`. Its exact allowlist includes the bounded Wasm backend and native C
generator, with no Core or research modules. The builder applies nine explicit,
reviewed branding substitutions to docstrings, the generated C header, and
semantic/checker version labels. Private compiler sources remain unchanged.
The branded package produces the same outputs and resource metrics, but its
plan digests differ; do not interchange plans or verification identities between
the private and public distributions. The package tests compare both versions.
The ZIP can prepare compiled Wasm and generate standalone finite-plan C programs
without the private checkout. The Performance page also provides the comparison
C and Rust sources; both programs are compiled before execution timing starts.

The built site needs only static HTTP/HTTPS hosting. The entire computation runs
in a Web Worker in the visitor's browser; source and input data stay there. All
runtime files are served from the site's own origin. A prepared Wasm instance is
reused while the exact source stays unchanged; every invocation validates its
inputs and compares the complete observation with a fresh evaluation of the
retained source. Relative URLs support a
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

The owner created the public repository and enabled Pages after the integration
returned403 for those administrative operations. The initial approved release was
commit `7a608cb` on `NtEuphoria/axiom-playground`. Updates publish from `main` at the
root directory. Actual Chromium execution and selected served-file hashes/MIME
types passed against the live HTTPS site. See the presentation review for evidence.

## A two-minute presentation

1. Start with **Fewer calculations** and the increasing input pattern. Explain:
   add 1 to each input, square it, then sum each neighboring 2 × 2 group. The code
   allows 64 bytes of temporary plan storage without specifying how to run.
   Press **Run computation**.
2. Show the output first: all 35 values match a separate calculation of the source.
   The selected plan keeps two rows, using 48 multiplications and 64 bytes of
   temporary plan storage.
3. Choose **No temporary storage** and run again. Axiom chooses inline execution:
   140 multiplications, zero temporary plan storage, and the same output.
4. Choose **Least storage**. Explain that the preferred resource can change the
   selected plan. Expand **Compare all three plans** to see the candidates.
5. Edit a source dimension or input pattern and run again to show real execution.
   Try zeros: every output becomes4. Download the current report for a record.

If showing errors, use an unsupported computation or custom input containing1024.
The program must report rejection instead of presenting an old success as current.

Use **Reset example** beside Run computation to start over. It restores **Fewer
calculations** and the increasing-number input pattern, clears the custom input
and previous report or diagnostic, and leaves the page ready to run. The button
is available once examples load, including while a computation is running.

For maintenance, `resetExample()` restores `examples[0].source` and input mode
`ramp`, then uses the existing `invalidate()` path. That path aborts the active
request and increments its request ID, so an old response cannot replace the
reset state or a newer run. The transport forwards cancellation to local fetches
or terminates a running browser worker; a subsequent browser run starts a fresh
runtime. Cancelling a local fetch stops the client waiting; server execution
remains bounded by its existing deadline. An immediate local rerun waits for
that worker by retrying only an explicit `429 WORKER_BUSY` response, every
250 milliseconds within the same 15-second request timeout. Reset or an edit
also cancels that wait. Other HTTP errors are not retried. Reset leaves keyboard
focus on the button and announces readiness through the existing status region.

## Exactly what works

The current profile accepts one two-stage stencil: square each input plus one,
then add four neighboring producer values in the source's prescribed grouping.
Names, positive H/W shapes, comments, scratch cap, and objective may change.
The maximum input is256 cells: `(H+1)*(W+1) <= 256`. A15×15 output fits;32×32 does
not. Input values are exact integers0..1023; arithmetic is checked i32.

All three candidate schedules are checked against source. The chosen plan is
checked again before interpreter execution or Wasm emission; compiled invocations
enforce the admitted input precondition. Saved success flags grant no authority.
Execution and the source evaluator operate independently and their complete
observations must agree. The browser uses the real Python compiler to produce
an import-free Wasm module with one fixed memory page. Source changes trigger
fresh selection, checking, and compilation; changing inputs reuses the prepared
module and still requires an independent comparison on every run.

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

For correctness-audited timings and an optional 20-million-number Python
file-output baseline, see [Local performance audit](benchmarks.md).

From the repository root, Node.js can run the dependency-free UI and transport
regressions (reset defaults, report clearing, cancellation, stale responses, and
immediate reruns):

```sh
node --test --test-timeout=5000 tools/test-playground-ui.cjs
```

From `axiom/`:

```sh
PYTHONPATH=src python3 -m unittest tests.test_runtime tests.test_playground_service tests.test_playground_http tests.test_playground_site -v
PYTHONPATH=src python3 -O -m unittest tests.test_runtime tests.test_playground_service tests.test_playground_http -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The full suite includes separately gated native tests. Skips are not native
qualification. See the retained presentation review for the actual current run.

Optional compiled-browser verification uses Playwright and Chromium installed
separately as developer tools, not runtime dependencies. Serve the generated
static release directory, then use its URL (or the hosted playground):

```sh
node tools/check-playground-browser.cjs http://YOUR_TEST_SERVER
```

Run that command from the repository root. `PLAYWRIGHT_MODULE` can select an
existing Playwright installation and `CHROMIUM_PATH` an existing browser binary.
`PLAYWRIGHT_PROXY` can select an existing network proxy when testing a public site;
TLS verification remains enabled.
It exercises actual execution, output equality, schedule changes, downloads,
rejections, stale-result clearing, keyboard reset after reports and diagnostics,
default restoration and rerunning, narrow screens, keyboard navigation, compiled
reuse, visible compilation costs, and both performance tables. The legacy HTTP
service remains covered by its Python tests.

## Compilation measurement contract

Research tooling lives outside the public site: `tools/profile-compilation.py`
and `tools/benchmarks/compilation.cjs`. Existing `tools/compare-playground.py`
measurements remain **precompiled process execution**; its separately visible
compilation fields now also retain C/plan/operation and executable sizes. Native
compiler flags and exact hashes stay alongside those fields.

An optional request-local `CompilationTrace` accepts `phase(name)` contexts and
`count(name, amount=1)` events. Callers use `trace=None` when disabled; no global
production functions are wrapped. `report()` returns schema version 1 with
`timing_unit: "ns"`, `timing_semantics: "inclusive"`, a `phases` mapping from names
to `{elapsed_ns, calls}`, and a separate integer `counts` mapping. Exceptions
still close a phase. Nested timings overlap and must not be summed. These
observational counts/times neither replace nor modify deterministic checker work
receipts, quotas, eligibility, or selection policy.

Canonical phase names are `source_admission`, `candidate_generation`,
`structural_validation`, `semantic_checking`, `canonical_encoding`,
`internal_decode`, `loop_correspondence`, `code_emission`,
`native_compiler_link`, `wasm_compile`, `wasm_instantiate`, `first_execution`,
`verification`, `total_fresh_source_preparation`, and `total_app_boot`. Optional
subphases and counter names may be added without changing schema version 1.
An absent phase/count means **not observed/instrumented**, rather than zero work.
Browser phases use the same inclusive interpretation with millisecond fields;
Python diagnostic traces retain their own nanosecond unit.

Fresh-source/runtime-ready measurements exclude runtime loading and imports,
which are retained separately. A changing source comment can produce identical
Wasm bytes; engine code reuse is uncontrolled in the browser harness's
`source-fresh` mode. Its `engine-cold` mode instead launches a fresh Chromium
process with a fresh temporary profile and Worker for every source/sample and
revision. Runtime boot/imports complete before the first user program is timed;
there is no warmup of that program. First execution is separate because engines
may compile lazily. Each artifact runs on two changing valid inputs and both
complete observations are checked against the retained original AST and an
external stencil formula. Diagnostic cProfile/trace preparations follow the
measured executions and are labeled separately.

See [research harness instructions](../../tools/benchmarks/compilation.md) for
paired checkout/site commands, the boundary fixture matrix, retained identities,
and limitations. These tools report observations; they do not qualify scalable
plan v2 or assert an implementation speedup by themselves.
