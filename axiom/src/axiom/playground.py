"""Loopback-only HTTP boundary for the checked Axiom presentation demo.

This intentionally small server serves fixed bundled assets and runs one fixed
Python worker at a time. It is intended for local presentation, not hosting.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading


MAX_BODY_BYTES = 131072
SOCKET_TIMEOUT = 5.0
WORKER_TIMEOUT = 10.0
MAX_RESPONSE_BYTES = 1048576
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_ASSETS = Path(__file__).resolve().parent / "playground_web"
_STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/transport.js": ("transport.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON number")


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _strict_json(raw):
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique_object,
        parse_constant=_reject_constant, parse_float=_finite_float,
    )


def _valid_payload(payload):
    if type(payload) is not dict:
        return False
    if type(payload.get("source")) is not str or type(payload.get("input_mode")) is not str:
        return False
    mode = payload["input_mode"]
    if mode not in ("ramp", "zeros", "checkerboard", "custom"):
        return False
    keys = {"source", "input_mode", "inputs"} if mode == "custom" else {"source", "input_mode"}
    if set(payload) != keys or (mode == "custom" and type(payload["inputs"]) is not list):
        return False
    try:
        payload["source"].encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


class _PlaygroundServer(ThreadingHTTPServer):
    # Browser pre-opened sockets must not stall asset/API requests. Bound both
    # connection threads and compiler concurrency instead of serializing reads.
    daemon_threads = False

    def __init__(self, address, handler):
        self._connections = threading.BoundedSemaphore(16)
        self.worker_lock = threading.Lock()
        super().__init__(address, handler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(SOCKET_TIMEOUT)
        return connection, address

    def process_request(self, request, client_address):
        if not self._connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connections.release()


class _Handler(BaseHTTPRequestHandler):
    server_version = "AxiomPlayground/1"
    sys_version = ""

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # A closed browser tab is an ordinary disconnect, not a source log.
            pass

    def log_message(self, format, *args):
        # BaseHTTPRequestHandler logs request paths; submitted source must never
        # enter server logs, even when put in a malformed request path.
        pass

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", _CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, value):
        self._send(status, json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8"))

    def _error(self, status, code, message):
        self._json(status, {"schema_version": 1, "status": "error", "diagnostic": {
            "code": code, "message": message, "offset": None,
        }})

    def send_error(self, code, message=None, explain=None):
        # Do not reflect the request line in BaseHTTPRequestHandler's HTML error
        # template. Parse errors are constant JSON responses too.
        self._error(code, "HTTP_ERROR", HTTPStatus(code).phrase)

    def _local_request(self):
        port = self.server.server_address[1]
        hosts = self.headers.get_all("Host", [])
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        if len(hosts) != 1 or hosts[0].lower() not in allowed:
            self._error(403, "HOST_REJECTED", "Use the playground's loopback address and port.")
            return False
        origins = self.headers.get_all("Origin", [])
        if origins and (len(origins) != 1 or origins[0] != "http://" + hosts[0].lower()):
            self._error(403, "ORIGIN_REJECTED", "The request origin must match this playground.")
            return False
        sites = self.headers.get_all("Sec-Fetch-Site", [])
        if sites and (len(sites) != 1 or sites[0] not in ("same-origin", "none")):
            self._error(403, "FETCH_SITE_REJECTED", "Cross-site playground requests are disabled.")
            return False
        return True

    def do_GET(self):
        if not self._local_request():
            return
        if self.path == "/api/health":
            self._json(200, {"schema_version": 1, "status": "ok"})
        elif self.path == "/api/examples":
            from .playground_service import get_examples

            self._json(200, get_examples())
        elif self.path in _STATIC_ROUTES:
            filename, content_type = _STATIC_ROUTES[self.path]
            try:
                content = (_ASSETS / filename).read_bytes()
            except OSError:
                self._error(503, "ASSET_UNAVAILABLE", "A bundled playground asset is unavailable.")
                return
            self._send(200, content, content_type)
        else:
            self._error(404, "NOT_FOUND", "This playground route does not exist.")

    def do_POST(self):
        if not self._local_request():
            return
        if self.path != "/api/run":
            self._error(404, "NOT_FOUND", "This playground route does not exist.")
            return
        if self.headers.get_all("Transfer-Encoding"):
            self._error(400, "INVALID_LENGTH", "Transfer encoding is not accepted.")
            return
        lengths = self.headers.get_all("Content-Length", [])
        if not lengths:
            self._error(411, "LENGTH_REQUIRED", "Content-Length is required.")
            return
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
            self._error(400, "INVALID_LENGTH", "Content-Length must be a single nonnegative integer.")
            return
        if len(lengths[0]) > 10 or int(lengths[0]) > MAX_BODY_BYTES:
            self._error(413, "BODY_TOO_LARGE", "The request body exceeds 131072 bytes.")
            return
        length = int(lengths[0])
        content_types = self.headers.get_all("Content-Type", [])
        media_type = tuple(part.strip().lower() for part in content_types[0].split(";")) if len(content_types) == 1 else ()
        if media_type not in (("application/json",), ("application/json", "charset=utf-8")):
            self._error(415, "CONTENT_TYPE_REQUIRED", "Use application/json with UTF-8 encoding.")
            return
        try:
            raw = self.rfile.read(length)
        except (TimeoutError, socket.timeout):
            self._error(408, "BODY_TIMEOUT", "The request body was not received in time.")
            return
        if len(raw) != length:
            self._error(400, "INCOMPLETE_BODY", "The request body ended before Content-Length.")
            return
        try:
            payload = _strict_json(raw)
        except (ValueError, UnicodeError, RecursionError):
            self._error(400, "INVALID_JSON", "Supply one strict UTF-8 JSON object without duplicate keys.")
            return
        if not _valid_payload(payload):
            self._error(400, "INVALID_REQUEST", "Supply source, input_mode, and inputs only for custom input.")
            return
        self._run_worker(raw)

    def _run_worker(self, raw):
        if not self.server.worker_lock.acquire(blocking=False):
            self._error(429, "WORKER_BUSY", "A computation is already running. Try again shortly.")
            return
        try:
            self._execute_worker(raw)
        finally:
            self.server.worker_lock.release()

    def _execute_worker(self, raw):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(_PACKAGE_ROOT)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "axiom.playground_service"],
                input=raw, capture_output=True, timeout=WORKER_TIMEOUT,
                cwd=str(_PACKAGE_ROOT), env=environment, check=False,
            )
        except subprocess.TimeoutExpired:
            self._error(504, "WORKER_TIMEOUT", "The computation exceeded the 10-second presentation limit.")
            return
        except OSError:
            self._error(502, "WORKER_FAILED", "The checked execution worker could not start.")
            return
        if result.returncode != 0 or len(result.stdout) > MAX_RESPONSE_BYTES:
            self._error(502, "WORKER_FAILED", "The checked execution worker did not complete normally.")
            return
        try:
            response = _strict_json(result.stdout)
            if (type(response) is not dict or response.get("schema_version") != 1
                    or response.get("status") not in ("success", "input_precondition_failed", "no_eligible_plan", "error")):
                raise ValueError("invalid worker response")
        except (ValueError, UnicodeError, RecursionError):
            self._error(502, "WORKER_FAILED", "The checked execution worker returned an invalid response.")
            return
        self._json(200, response)

    def _unsupported_method(self):
        if self._local_request():
            self._error(405, "METHOD_NOT_ALLOWED", "Use GET for assets and POST for a computation.")

    do_OPTIONS = _unsupported_method
    do_HEAD = _unsupported_method
    do_PUT = _unsupported_method
    do_PATCH = _unsupported_method
    do_DELETE = _unsupported_method


def create_server(port=8765):
    """Create an unstarted loopback server; port 0 chooses a free local port."""
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("port must be an integer between 0 and 65535")
    return _PlaygroundServer(("127.0.0.1", port), _Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the local checked Axiom playground.")
    parser.add_argument("--port", type=int, default=8765, help="loopback TCP port (default: 8765)")
    arguments = parser.parse_args(argv)
    if not 0 <= arguments.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        server = create_server(arguments.port)
    except OSError as error:
        parser.exit(1, f"Could not start the local playground: {error.strerror}\n")
    previous_break_handler = None
    try:
        if sys.platform == "win32":
            # Treat Windows Ctrl+Break like Ctrl+C so normal cleanup runs.
            previous_break_handler = signal.signal(signal.SIGBREAK, signal.default_int_handler)
        print(f"Axiom playground: http://127.0.0.1:{server.server_address[1]}", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if previous_break_handler is not None:
            signal.signal(signal.SIGBREAK, previous_break_handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
