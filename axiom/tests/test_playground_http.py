"""Behavioral tests for the loopback-only presentation HTTP boundary."""

import contextlib
import http.client
import importlib
import importlib.util
import io
import json
from pathlib import Path
import queue
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock


class HTTPFixture(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("axiom.playground"),
            "The bounded loopback HTTP server has not been implemented",
        )
        self.playground = importlib.import_module("axiom.playground")
        self.server = self.playground.create_server(port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.port = self.server.server_address[1]
        self.host = f"127.0.0.1:{self.port}"

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())

    def request(self, method="GET", path="/api/health", body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        self.addCleanup(connection.close)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def raw(self, headers, body=b"", *, half_close=False):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as client:
            client.sendall(headers + b"\r\n\r\n" + body)
            if half_close:
                client.shutdown(socket.SHUT_WR)
            response = bytearray()
            while chunk := client.recv(65536):
                response.extend(chunk)
        head, payload = bytes(response).split(b"\r\n\r\n", 1)
        return int(head.split(b" ", 2)[1]), head, payload

    def post(self, body, headers=None):
        values = {"Content-Type": "application/json"}
        values.update(headers or {})
        return self.request("POST", "/api/run", body, values)


class PlaygroundBoundaryTests(HTTPFixture):
    def test_health_is_loopback_and_has_browser_security_headers(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_host_requires_loopback_name_and_actual_port(self):
        for host in ("example.com", f"evil.test:{self.port}", "localhost", "127.0.0.1:1",
                     f"127.0.0.1.evil.test:{self.port}"):
            with self.subTest(host=host):
                self.assertEqual(self.request(headers={"Host": host})[0], 403)
        for host in (self.host, f"localhost:{self.port}", f"[::1]:{self.port}"):
            with self.subTest(host=host):
                self.assertEqual(self.request(headers={"Host": host})[0], 200)

    def test_missing_and_duplicate_host_are_rejected(self):
        for host_lines in (b"", f"Host: {self.host}\r\nHost: evil.test\r\n".encode()):
            with self.subTest(host_lines=host_lines):
                self.assertEqual(self.raw(b"GET /api/health HTTP/1.1\r\n" + host_lines.rstrip(b"\r\n"))[0], 403)

    def test_origin_must_match_request_host(self):
        for origin in ("null", "https://evil.test", f"http://localhost:{self.port}",
                       f"https://{self.host}", f"http://{self.host}/"):
            with self.subTest(origin=origin):
                self.assertEqual(self.request(headers={"Origin": origin})[0], 403)
        self.assertEqual(self.request(headers={"Origin": f"http://{self.host}"})[0], 200)

    def test_duplicate_origin_and_cross_site_fetch_metadata_are_rejected(self):
        raw = (f"GET /api/health HTTP/1.1\r\nHost: {self.host}\r\n"
               f"Origin: http://{self.host}\r\nOrigin: http://{self.host}").encode()
        self.assertEqual(self.raw(raw)[0], 403)
        for site in ("cross-site", "same-site", "unrecognised"):
            self.assertEqual(self.request(headers={"Sec-Fetch-Site": site})[0], 403)
        self.assertEqual(self.request(headers={"Sec-Fetch-Site": "same-origin"})[0], 200)

    def test_only_explicit_static_and_api_routes_are_served(self):
        for path in ("/../README.md", "/%2e%2e/README.md", "/axiom/", "/app.js?x=1",
                     "/api/health?x=1", "/etc/passwd", "/api/run"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path=path)[0], 404)
        self.assertEqual(self.request("POST", "/api/health", b"{}")[0], 404)
        self.assertEqual(self.request("OPTIONS", "/api/run")[0], 405)

    def test_json_content_type_is_required(self):
        for content_type in ("text/plain", "application/x-www-form-urlencoded", "application/json; charset=latin-1",
                             "application / json", "application/json; char set=utf-8"):
            self.assertEqual(self.post(b"{}", {"Content-Type": content_type})[0], 415)

    def test_duplicate_content_type_is_rejected(self):
        headers = (f"POST /api/run HTTP/1.1\r\nHost: {self.host}\r\n"
                   "Content-Type: application/json\r\nContent-Type: text/plain\r\n"
                   "Content-Length: 2").encode()
        self.assertEqual(self.raw(headers, b"{}")[0], 415)

    def test_length_is_required_unambiguous_and_bounded_before_body_read(self):
        prefix = f"POST /api/run HTTP/1.1\r\nHost: {self.host}\r\nContent-Type: application/json".encode()
        cases = ((b"", 411), (b"\r\nContent-Length: -1", 400),
                 (b"\r\nContent-Length: +2", 400), (b"\r\nContent-Length: 2, 2", 400),
                 (b"\r\nContent-Length: 2\r\nContent-Length: 2", 400),
                 (b"\r\nContent-Length: 131073", 413),
                 (b"\r\nTransfer-Encoding: chunked", 400),
                 (b"\r\nTransfer-Encoding: chunked\r\nContent-Length: 2", 400))
        for suffix, expected in cases:
            with self.subTest(suffix=suffix):
                self.assertEqual(self.raw(prefix + suffix)[0], expected)

    def test_short_request_body_is_rejected(self):
        headers = (f"POST /api/run HTTP/1.1\r\nHost: {self.host}\r\n"
                   "Content-Type: application/json\r\nContent-Length: 10").encode()
        self.assertEqual(self.raw(headers, b"{}", half_close=True)[0], 400)

    def test_stalled_request_body_times_out(self):
        headers = (f"POST /api/run HTTP/1.1\r\nHost: {self.host}\r\n"
                   "Content-Type: application/json\r\nContent-Length: 10").encode()
        with mock.patch.object(self.playground, "SOCKET_TIMEOUT", 0.05):
            self.assertEqual(self.raw(headers, b"{}")[0], 408)

    def test_idle_browser_connection_does_not_block_other_requests(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as idle:
            idle.sendall(b"GET / HTTP/1.1\r\n")
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=0.5)
            try:
                connection.request("GET", "/api/health")
                try:
                    response = connection.getresponse()
                except TimeoutError:
                    self.fail("An idle browser connection blocked an independent health request")
                self.assertEqual(response.status, 200)
                response.read()
            finally:
                connection.close()

    def test_overlapping_compiler_requests_are_rejected_without_starting_another_worker(self):
        entered, release = threading.Event(), threading.Event()
        first_response = queue.Queue()

        def hold_worker(*args, **kwargs):
            entered.set()
            release.wait(timeout=5)
            return subprocess.CompletedProcess([], 0, b'{"schema_version":1,"status":"error"}', b"")

        with mock.patch.object(self.playground.subprocess, "run", side_effect=hold_worker) as worker:
            first = threading.Thread(target=lambda: first_response.put(self.post(b'{"source":"x","input_mode":"zeros"}')))
            first.start()
            try:
                self.assertTrue(entered.wait(timeout=5))
                connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=0.5)
                try:
                    connection.request("POST", "/api/run", b'{"source":"x","input_mode":"zeros"}',
                                       {"Content-Type": "application/json"})
                    try:
                        response = connection.getresponse()
                    except TimeoutError:
                        self.fail("An overlapping run did not receive an immediate busy response")
                    self.assertEqual(response.status, 429)
                    self.assertEqual(json.loads(response.read())["diagnostic"]["code"], "WORKER_BUSY")
                finally:
                    connection.close()
                self.assertEqual(worker.call_count, 1)
            finally:
                release.set()
                first.join(timeout=5)
        self.assertEqual(first_response.get(timeout=1)[0], 200)

    def test_json_is_strict_and_top_level_payload_is_exact(self):
        bodies = (b"", b"{", b"[]", b"null", b"{}",
                  b'{"source":"x","source":"y","input_mode":"zeros"}',
                  b'{"source":"x","input_mode":"custom","inputs":[NaN]}',
                  b'{"source":"x","input_mode":"custom","inputs":[Infinity]}',
                  b'{"source":"x","input_mode":"custom","inputs":[1e999]}',
                  b'{"source":"x","input_mode":"zeros","command":"id"}',
                  b'{"source":"x","input_mode":"zeros","inputs":[]}',
                  b'{"source":true,"input_mode":"zeros"}',
                  b'{"source":"x","input_mode":"custom"}',
                  b'{"source":"x","input_mode":"custom","inputs":{}}',
                  b'{"source":"\\ud800","input_mode":"zeros"}',
                  b'{"source":"x","input_mode":"unknown"}', b"\xff",
                  b'[' * 2000 + b']' * 2000)
        with mock.patch.object(self.playground.subprocess, "run") as worker:
            for body in bodies:
                with self.subTest(body=body[:100]):
                    self.assertEqual(self.post(body)[0], 400)
            worker.assert_not_called()

    def test_body_limit_applies_to_utf8_bytes(self):
        body = json.dumps({"source": "x" * 131072, "input_mode": "zeros"}).encode()
        self.assertEqual(self.post(body)[0], 413)

    def test_worker_timeout_returns_stable_error_without_source_or_traceback(self):
        secret = "private-source-MARKER"
        error = subprocess.TimeoutExpired([sys.executable], 10, output=secret.encode(), stderr=b"private stderr")
        with mock.patch.object(self.playground.subprocess, "run", side_effect=error):
            status, _, body = self.post(json.dumps({"source": secret, "input_mode": "zeros"}))
        self.assertEqual(status, 504)
        self.assertEqual(json.loads(body)["diagnostic"]["code"], "WORKER_TIMEOUT")
        self.assertNotIn(secret.encode(), body)
        self.assertNotIn(b"private stderr", body)

    def test_worker_crash_invalid_output_and_spawn_failure_are_closed(self):
        for outcome in (subprocess.CompletedProcess([], 1, b"private source", b"traceback"),
                        subprocess.CompletedProcess([], 0, b"not-json", b""),
                        subprocess.CompletedProcess([], 0, b"[]", b""),
                        subprocess.CompletedProcess([], 0, b'{"status":"success","status":"error"}', b""),
                        OSError("private filesystem path")):
            with self.subTest(outcome=type(outcome).__name__):
                kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with mock.patch.object(self.playground.subprocess, "run", **kwargs):
                    status, _, body = self.post(b'{"source":"x","input_mode":"zeros"}')
                self.assertEqual(status, 502)
                self.assertEqual(json.loads(body)["status"], "error")
                self.assertNotIn(b"private", body)

    def test_requests_do_not_log_submitted_source_or_paths(self):
        logs = io.StringIO()
        with contextlib.redirect_stderr(logs), contextlib.redirect_stdout(logs):
            self.post(b'{"source":"secret-source-token","input_mode":"bad"}')
            self.request(path="/secret-path-token")
        self.assertEqual(logs.getvalue(), "")


class PlaygroundIntegrationTests(HTTPFixture):
    def test_all_bundled_assets_are_served_without_external_dependencies(self):
        for path, content_type in (("/", "text/html"), ("/app.js", "text/javascript"),
                                   ("/transport.js", "text/javascript"), ("/style.css", "text/css")):
            with self.subTest(path=path):
                status, headers, body = self.request(path=path)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith(content_type))
                self.assertGreater(len(body), 10)

    def test_real_worker_selects_checks_executes_and_compares(self):
        status, _, body = self.request(path="/api/examples")
        self.assertEqual(status, 200)
        examples = {example["id"]: example for example in json.loads(body)["examples"]}
        self.assertEqual(set(examples), {"balanced", "no-scratch", "small-memory"})
        status, _, body = self.post(json.dumps({"source": examples["balanced"]["source"], "input_mode": "ramp"}))
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected"]["plan_id"], "rows2-v1")
        self.assertEqual(result["comparison"], {"matches": True, "cells_compared": 35})
        self.assertEqual((result["output"][0], result["output"][-1]), (186, 7634))

    def test_body_at_exact_limit_reaches_the_worker_and_invalid_source_is_not_executed(self):
        # Arbitrary Python text is parsed only as Axiom and cannot become code.
        request = json.dumps({"source": "raise RuntimeError('never execute')", "input_mode": "zeros"}).encode()
        status, _, body = self.post(request.ljust(131072, b" "))
        self.assertEqual(status, 200)
        response = json.loads(body)
        self.assertEqual(response["status"], "error")
        self.assertNotEqual(response["diagnostic"]["code"], "INTERNAL_ERROR")

    def test_real_worker_ignores_import_shadow_from_unrelated_working_directory(self):
        # A lookalike module in the HTTP process's cwd must not become code.
        import os
        original = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            fake_package = Path(directory) / "axiom"
            fake_package.mkdir()
            marker = Path(directory) / "WRONG_IMPORT"
            (fake_package / "__init__.py").write_text(
                "from pathlib import Path\nPath('WRONG_IMPORT').write_text('loaded')\n")
            (fake_package / "playground_service.py").write_text("raise RuntimeError('wrong worker')\n")
            try:
                os.chdir(directory)
                _, _, raw_examples = self.request(path="/api/examples")
                source = json.loads(raw_examples)["examples"][0]["source"]
                status, _, body = self.post(json.dumps({"source": source, "input_mode": "zeros"}))
            finally:
                os.chdir(original)
            self.assertFalse(marker.exists())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["output"], [4] * 35)

    def test_real_cli_starts_on_loopback_and_stops_cleanly(self):
        import os
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(self.playground.__file__).resolve().parent.parent)
        # Windows console events must target an isolated process group.
        windows = sys.platform == "win32"
        process = subprocess.Popen(
            [sys.executable, "-m", "axiom.playground", "--port", "0"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if windows else 0,
        )
        def close_process():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

        self.addCleanup(close_process)
        output = queue.Queue()
        reader = threading.Thread(target=lambda: output.put(process.stdout.readline()), daemon=True)
        reader.start()
        line = output.get(timeout=5)
        self.assertTrue(line.startswith("Axiom playground: http://127.0.0.1:"), line)
        port = int(line.rsplit(":", 1)[1])
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("GET", "/api/health")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["status"], "ok")
        finally:
            connection.close()
            process.send_signal(signal.CTRL_BREAK_EVENT if windows else signal.SIGINT)
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual((process.returncode, stdout, stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
