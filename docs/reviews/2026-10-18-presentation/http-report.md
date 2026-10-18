# Local playground HTTP implementation

Implemented only:

- `axiom/src/axiom/playground.py`
- `axiom/tests/test_playground_http.py`

The server binds exclusively to `127.0.0.1`. Canonical loopback Host values must
include the actual port, supplied Origin must match, and cross-site fetch
metadata is refused. The only static routes are `/`, `/app.js`, `/transport.js`,
and `/style.css`; JSON routes are `/api/health`, `/api/examples`, and `/api/run`.
The browser-only worker and compiler archive are not served by the local server.

Run requests have a 131072-byte body limit, single decimal Content-Length,
unambiguous framing, application/json media type, strict UTF-8 JSON without
duplicates/non-finite values, exact request fields, and a five-second socket
inactivity timeout. The fixed worker command is `sys.executable -m
axiom.playground_service`, with no shell, a ten-second process timeout, and a
fixed absolute package cwd/PYTHONPATH. Source is only worker input. Worker errors
are stable JSON without subprocess stderr, traceback, or source logs.

There are at most 16 accepted connection threads and one active compiler worker.
A second run receives 429 WORKER_BUSY. Threaded reads prevent speculative idle
browser sockets from blocking legitimate asset or API requests. Shutdown waits
for bounded active handlers and CLI Ctrl+C exits normally. Responses carry a
restrictive CSP, nosniff, no-store, no-referrer, and no CORS permission headers.

## Verification

All commands ran from `/workspace/BerylLattice-o3-fixes`.

Initial RED: `PYTHONPATH=axiom/src:axiom python -m unittest
tests.test_playground_http` failed because the server module did not exist.
The original 18 test failures are retained in `http-red.log`.

Additional RED regressions retained:

- `http-red-content-type.log`: malformed interior-spaced MIME type reached JSON
  validation (400) instead of being rejected as an unsupported content type (415).
- `http-red-concurrency.log`: both an idle connection and an active worker blocked
  unrelated requests in the initially serial server. Both tests failed before
  bounded threaded handling and the worker lock were added.

Final GREEN, exit 0:

```
PYTHONPATH=axiom/src:axiom python -m unittest tests.test_playground_http
Ran 23 tests in 11.163s — OK
```

Final optimized Python GREEN, exit 0:

```
PYTHONPATH=axiom/src:axiom python -O -m unittest tests.test_playground_http
Ran 23 tests in 11.670s — OK
```

Logs: `http-green.log` and `http-optimized.log`. `git diff --check` passed.

The suite includes real HTTP and subprocess execution selecting rows2-v1,
comparing all 35 outputs, checking first186/last7634; an exact-limit request;
rejection of executable-looking source as invalid Axiom; startup and clean
Ctrl+C; and a hostile shadow package in an unrelated cwd that cannot be imported
by the worker. Fault injection is limited to timeouts, worker failures/output,
socket deadlines, and holding one worker for a deterministic concurrency check.

Normal and optimized targeted tests are complete. The parent agent owns the
final full product suite and browser checks after all parallel changes settle.
These are presentation HTTP tests, not O3 qualification evidence. No Core files,
service code, assets, docs, Git commits, or external publication were changed by
this subtask.

Final reviewed-file SHA256:

```
e70675ae47f1859b711a034b831afa7083e4dfacb94fcb3c972172bfa974af39  axiom/src/axiom/playground.py
475f48785c4d8c4744328ba747324192e6dc99c65fb8a86cf747cd5de74afab6  axiom/tests/test_playground_http.py
```
