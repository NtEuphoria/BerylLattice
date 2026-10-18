# Static browser playground implementation and evidence

Date: 2026-10-18. No deployment, public repository, registration, message, or
privacy change was made by this agent. Root owns the final UI/release freeze.

## Owned source changes

- `axiom/src/axiom/playground_web/transport.js`: async `getExamples` and `runDemo`
  use the same local JSON API by default; `html[data-runtime=browser]` uses a
  Web Worker. Limits requests to131072 UTF-8 bytes, boot to60seconds, runs to15
  seconds. A timeout terminates the Worker and rejects pending requests; retry
  constructs a new Worker. Concurrent execution rejects explicitly.
- `axiom/src/axiom/playground_web/worker.js`: loads Pyodide, unpacks the compiler,
  imports real `get_examples` / `run_demo`, uses the existing strict JSON parser,
  and returns canonical JSON. It does not evaluate user text as Python.
- `tools/build-playground-site.py`: builds a new/empty local directory, preserving
  any nonempty destination. Explicit allowlists package5 web assets and exactly11
  Python modules. No research, Core, receipts, recovery records, Git history,
  arbitrary source globs, or local logs are copied. It stamps browser runtime,
  relative asset paths, CSP, same-origin runtime configuration, source ZIP,
  release README, hosting headers, and complete file/module SHA256 manifest.
- `axiom/tests/test_playground_site.py`:2 tests. Real source ZIP executes in an
  isolated Python subprocess without repository imports; manifest covers every
  emitted file; exact module allowlist excludes private research; nonempty
  output remains unchanged.

Source hashes at this report:

```
12c9ff21ac41766ccec06c41dc196bc99055ccd9be4575646b9afae101ae8e4b transport.js
f01138516637a4ee1d9f5ad3b98b1e536b4d02a4c1420097cd11fabe3cba2211 worker.js
ae22cae133ee878051b29e89833fb43fd674d16c58c4f7e86866e5bfaa44c239 build-playground-site.py
80e153a1911376ba8bb1a426e203ec7c62dd153bf73f89546c297fb2fd43f2f1 test_playground_site.py
```

## Runtime dependency and publication scope

Default build vendors Pyodide0.27.7 / Python3.12.7. Five runtime files were fetched
from the pinned official distribution at
https://cdn.jsdelivr.net/pyodide/v0.27.7/full/ with normal TLS/proxy configuration,
then pinned by SHA256. Build rechecks every byte against those constants.
Pyodide MPL-2.0 and matching CPython license texts are bundled with their hashes
and source URLs. No license was assigned to Axiom. No Python packages are loaded
beyond the bundled stdlib. Cache directory used for repeatable offline rebuild:
`/workspace/scratch/axiom-presentation-2026-10-18/pyodide-cache`.

The build also has explicit `--runtime cdn` mode for quick packaging/tests. That
mode requires runtime internet/CDN trust; the README and manifest disclose it.
The reviewed runnable snapshot used the default vendor mode, not CDN mode.

The compiled source ZIP is directly downloadable and contains the actual11
compiler/runtime source modules. It is not encryption or secrecy. Public upload
of this folder reveals these modules and all UI files. Root requested UI links
for source ZIP and release README; the UI agent owns that final addition.

## Test evidence

- `static-red.log`: expected failure before builder existed.
- `static-green.log`: canonical command
  `PYTHONPATH=axiom/src python -m unittest discover -s axiom/tests -p test_playground_site.py -v`;
 2 tests passed. An intermediate assertion initially expected the shorthand
  rows2 instead of the real rows2-v1 ID; corrected to the actual stable contract.
  A later invocation mistakenly used `axiom/tests/...` together with PYTHONPATH,
  producing a test-import error; canonical discovery above then passed.
- `static-browser.log`: actual Chromium/Pyodide/Worker smoke runs all3 examples
  plus a malformed program. Balanced selects rows2-v1 (48multiplications,
 64scratch bytes); no-scratch and small-memory select inline-v1 (140multiplies,
 0scratch). Every35-cell output matches the source evaluator; first186,last7634.
  Malformed program rejects with UNSUPPORTED_PROFILE. Zero console errors. All12
  requested resources come from the same loopback origin under a subpath.
- `static-browser-csp.log`: the same real smoke also passes after adding a strict
  HTTP CSP to the Worker response: script-src self + wasm-unsafe-eval,
  connect-src self. No unsafe-eval or external origins are needed.
- `static-ui-browser.log`: root's real `tools/check-playground-browser.cjs`
  passes rows2 execution, exported report, cap changes, stale-result clearing,
  zero input, unsupported shape, invalid-input preservation,320/768/1024/1440
  widths, keyboard navigation, and no page errors.
- `static-timeout.log`: fault injection suppresses one Worker run response (the
  worker still boots the actual Python implementation). Advancing the page clock
  triggers the15-second timeout, terminates the Worker, then a retry creates a
  second Worker and completes a real compiler run (first output186).
- `node --check` passed for worker.js and transport.js; Python py_compile passed
  for the build script. Root runs overall product/research suites.

Browser scripts and logs remain in the same scratch evidence directory. The
first exploratory smoke called getExamples concurrently with UI initialization,
correctly receiving a busy error. The harness then awaited initialization. A
second initial smoke found a missing favicon404; generated HTML now supplies a
non-network favicon. Final smoke has no errors.

## Tested snapshot, not final publication bytes

`/workspace/scratch/axiom-presentation-2026-10-18/static-site-reviewed`
contains17files /13,964,639bytes. Manifest SHA256:
`9dcdd949d1749caff93f4eb5759b9b7372e6f28ee58777abff9ce3a0d56e8764`.
This snapshot passed browser checks, but UI review changes may follow. Root must
rebuild into a new empty folder and re-run the final browser check after freezing
all inputs. Command:

```
python tools/build-playground-site.py --output NEW_EMPTY_DIRECTORY \
  --runtime-cache /workspace/scratch/axiom-presentation-2026-10-18/pyodide-cache
PLAYWRIGHT_MODULE=/opt/codex/cua_node/lib/node_modules/playwright-core \
CHROMIUM_PATH=/usr/bin/chromium node tools/check-playground-browser.cjs \
  http://127.0.0.1:PORT/PUBLIC_SUBPATH/
```

A preview server remains on127.0.0.1:8877 serving the scratch parent directory;
it is a local test server and must not be used as the public hosting server.
It can be terminated when root finishes reviewing these snapshots.

## Definitive frozen-input build

After root confirmed the UI freeze, the definitive artifact was built at:

- `/workspace/scratch/axiom-presentation-2026-10-18/axiom-playground-site`
- `/workspace/scratch/axiom-presentation-2026-10-18/axiom-playground-site.zip`

The folder contains17 files and13,965,423 bytes. The deterministic ZIP has
5,784,582 bytes; its entries are sorted, timestamped2026-10-18 00:00:00, mode0644,
and deflated at level9, without a wrapping directory.

ZIP SHA256:
`5f47594f635ba7f98266b9deb53501682d367f249f119a1ee91e2c7f6fd6e8b4`

release-manifest.json SHA256:
`269f30d271e4a40b5d09928f9df3f85b3b25d82e4c32ef259307c067f019c287`

Final source UI hashes:

```
8241a9e87b0118583514f46d316254bcae00b05a4a28caf945f8c6d2af3a6cf7 index.html
fcf8337386ad2f045b8053302b0a85650d3b55af61465c3003975b137f6cfc8a app.js
af8329ebc631476071ab2761427a9f97d753e23ce96881c45aa8adf03ca37572 style.css
```

The four owned source hashes above remain unchanged. The manifest records all11
exact compiler module hashes. An independent readback of the outer ZIP verified
its exact17 entries and every size/hash against the manifest and folder. An
independent readback of the inner compiler ZIP verified all11 modules against
current working-tree sources.

`static-ui-browser-final.log` passes the full real UI check at
`http://127.0.0.1:8877/axiom-playground-site/`, explicitly a repository-style
subpath. The screenshot is `static-playground-final.png`.

`static-browser-final-csp.log` repeats actual compilation for all3 examples and
malformed input under strict Worker HTTP CSP. Zero console errors; all runtime
requests are same-origin under the final subpath. This artifact is ready for
publication scope review, not an assertion that it has been deployed.

## Approved MIT / GitHub Pages publication artifact (supersedes earlier builds)

The user subsequently approved the bounded demo under MIT in the separate
`NtEuphoria/axiom-playground` repository. The root agent owns public upload.
The final immutable artifact for that approval is:

- `/workspace/scratch/axiom-presentation-2026-10-18/axiom-playground-pages`
- `/workspace/scratch/axiom-presentation-2026-10-18/axiom-playground-pages.zip`

This19-file folder totals13,969,641bytes. The deterministic ZIP is5,786,433bytes.
ZIP SHA256:
`3591bc0bf259d51d2e0c55f319750e323192739c6dfa28b293311220201577f4`

Manifest SHA256:
`bdf1bd7bd5678a9f33f643f1a46deb1812381a9f72ca01a9a44f90a50f5f131c`

Compiler ZIP SHA256:
`abd6d1a35979e7f3901d5dd2a25c4988540b0e055d4db9e4d7310a296efb1ffe`

Approved source change `axiom/playground-LICENSE` is standard MIT, copyright2026
NtEuphoria. The generated README scopes the license to the11 Python compiler
modules,5 UI/transport assets, and accompanying demo documentation; it expressly
excludes private research/recovery/Core material. Third-party runtime licenses
remain separate. LICENSE is included both at site root and inside the standalone
compiler source ZIP. `compiler_modules` still records11 Python modules;
`compiler_archive_members` records all12 ZIP members, including LICENSE.
Empty `.nojekyll` is included in the site, outer ZIP, and manifest, so GitHub
Pages serves the intended static release without Jekyll processing.

Final changed-source hashes:

```
673f0bfcb392c499679e681044b81018222fdcfe14ad3adffc8d4735f89e62aa axiom/playground-LICENSE
f69dcfaf6c0faf44bf2cd73fc4e8dd03be97769d6e06ea89d797a257474549bf tools/build-playground-site.py
88f0b6c68ece9d8296250ea8a960a2a0d65ab1717779018a845df0b70a95f075 axiom/tests/test_playground_site.py
```

The compiler and UI/transport source bytes have not changed since the previous
real browser evidence. Licensing/site-marker regressions were each observed RED
before the implementation, then the2 packaging tests passed under normal Python
and Python -O (`static-license-*`, `static-archive-license-*`, `static-nojekyll-*`
logs). The final19-file outer ZIP was read back against every manifest hash and
the generated directory. The compiler ZIP's12 members were checked, with LICENSE
matching site-root LICENSE and all11 Python modules matching working-tree bytes.

`static-ui-browser-mit-final.log` passed the complete real UI browser suite after
the embedded-license change. The same19-file bytes as the final Pages artifact
also passed at `/axiom-playground-public/` (`static-ui-browser-public.log`); the
Pages directory differs only in its local directory name. No subsequent source
or release-artifact changes were made by this agent. Independent integration
reviewer received the final Pages path and hashes for its own final verification.
