"""Offline tests for the opt-in PulseDirector diagnostic contract.

No Lovense Remote network traffic, motors, cloud tokens or real sessions.
"""
import http.client
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import edge_dashboard
import pulsedirector_diagnostics as diag


class FakeEngine:
    def __init__(self):
        self.state_lock = threading.Lock()
        self.last_telemetry = time.monotonic() - 3
        self.toy_connected = True
        self.last_device_error = ""
        self.fault_reason = ""
        self.fault_latched = False
        self.stop_pending = False
        self.last_stop_error = ""
        self.active_route = "lan"
        self.simulate = False
        self.forbidden_calls = []

    def __getattr__(self, name):
        raise AssertionError("Unexpected engine attribute: " + name)

    def _forbidden(self, name):
        self.forbidden_calls.append(name)
        raise AssertionError("Diagnostic called a control/IO function: " + name)

    def status(self): return self._forbidden("status")
    def refresh_toys(self): return self._forbidden("refresh_toys")
    def _api(self, payload): return self._forbidden("_api")
    def start(self, body): return self._forbidden("start")
    def stop(self): return self._forbidden("stop")
    def test(self): return self._forbidden("test")
    def acknowledge_fault(self): return self._forbidden("acknowledge_fault")
    def _send_stop(self): return self._forbidden("_send_stop")


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path):
        super().__init__("localhost", timeout=3)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()

    def snap(self, profile="lan"):
        return diag.snapshot(self.engine, profile=profile,
                             started_monotonic=time.monotonic() - 12,
                             started_at_utc="2026-11-11T00:00:00+00:00")

    def test_snapshot_does_not_call_any_engine_methods(self):
        result = self.snap()
        self.assertEqual(self.engine.forbidden_calls, [])
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["application"]["version_family"]["value"], "v4.6")
        self.assertEqual(result["connection"]["last_known_state"]["value"], "reported_connected")
        self.assertFalse(result["connection"]["last_known_state"]["current_connection_verified"])
        self.assertEqual(result["stop"]["physical_motor_state"]["value"], "unverified")

    def test_no_fabricated_history(self):
        result = self.snap()
        for section, item in (("connection", "failure_count"),
                              ("connection", "last_disconnection_at"),
                              ("connection", "last_reconnection_at"),
                              ("session", "last_outcome"),
                              ("session", "last_interruption_category"),
                              ("recovery", "last_attempt"),
                              ("recovery", "last_outcome"),
                              ("stop", "last_request_outcome")):
            with self.subTest(section=section, item=item):
                self.assertFalse(result[section][item]["supported"])
                self.assertIsNone(result[section][item]["value"])
        self.assertEqual(result["events"]["retention_seconds"], 0)
        self.assertEqual(result["events"]["items"], [])

    def test_telemetry_age_can_be_stale_or_unavailable(self):
        self.engine.last_telemetry = time.monotonic() - 150
        self.assertEqual(self.snap()["connection"]["last_known_state"]["freshness"], "stale")
        self.engine.last_telemetry = None
        self.assertFalse(self.snap()["connection"]["last_known_state"]["supported"])

    def test_cloud_state_is_not_a_live_heartbeat(self):
        self.engine.active_route = "cloud"
        result = self.snap("hybrid")
        self.assertEqual(result["connection"]["last_known_state"]["value"], "unverified")
        self.assertFalse(result["connection"]["last_known_state"]["current_connection_verified"])

    def test_fault_and_stop_are_software_only(self):
        self.engine.fault_latched = True
        self.engine.fault_reason = "STOP NOT DELIVERED; 192.0.2.45 token=ultrasecret"
        self.engine.stop_pending = True
        self.engine.last_stop_error = "ultrasecret"
        result = self.snap()
        self.assertTrue(result["recovery"]["fault_latched"]["value"])
        self.assertTrue(result["recovery"]["pending"]["value"])
        self.assertTrue(result["stop"]["cached_error_present"]["value"])
        self.assertEqual(result["application"]["current_fault_category"]["value"],
                         "stop_delivery_failed")
        self.assertFalse(result["stop"]["last_request_outcome"]["supported"])

    def test_secret_and_error_text_never_serialized(self):
        self.engine.last_device_error = (
            "Cannot reach Lovense Remote at 192.0.2.45; "
            "token=ultrasecret callback=https://private.example/ "
            "UID=privateid QR=privatepair"
        )
        self.engine.fault_latched = True
        self.engine.fault_reason = "privatepair"
        self.engine.last_stop_error = "ultrasecret"
        text = json.dumps(self.snap())
        for sensitive in ("ultrasecret", "192.0.2.45", "private.example",
                          "privatepair", "privateid", "UID=", "QR="):
            self.assertNotIn(sensitive, text)
        self.assertEqual(self.snap()["connection"]["cached_error_category"]["value"],
                         "phone_game_mode_unreachable")

    def test_busy_lock_exits_quickly_without_mutating_state(self):
        self.engine.state_lock.acquire()
        before = time.monotonic()
        try:
            with self.assertRaises(diag.SnapshotUnavailable):
                self.snap()
        finally:
            self.engine.state_lock.release()
        self.assertLess(time.monotonic() - before, 0.5)


@unittest.skipUnless(hasattr(socket, "AF_UNIX") and os.name == "posix", "Unix sockets required")
class SocketTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.private = Path(self.td.name) / "private"
        self.private.mkdir(mode=0o700)
        self.path = self.private / "diagnostics.sock"
        self.engine = FakeEngine()
        self.server, self.thread = diag.start_private_diagnostics_server(
            str(self.path), self.engine, profile="lan")

    def tearDown(self):
        diag.stop_private_diagnostics_server(self.server, self.thread)
        self.td.cleanup()

    def request(self, method, path):
        conn = UnixHTTPConnection(str(self.path))
        try:
            conn.request(method, path)
            result = conn.getresponse()
            return result.status, result.headers, result.read().decode("utf-8")
        finally:
            conn.close()

    def test_socket_is_owner_only_and_cleanup(self):
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertTrue(stat.S_ISSOCK(self.path.stat().st_mode))
        self.assertEqual(self.path.stat().st_uid, os.geteuid())

    def test_get_versioned_diagnostics_only(self):
        status, headers, body = self.request("GET", "/api/diagnostics/v1")
        self.assertEqual(status, 200)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertEqual(json.loads(body)["schema_version"], 1)
        self.assertEqual(self.engine.forbidden_calls, [])
        self.assertLess(len(body), diag.MAX_RESPONSE_BYTES)

    def test_control_endpoints_dont_exist_on_diagnostics_server(self):
        for path in ("/api/start", "/api/stop", "/api/test",
                     "/api/ack-fault", "/api/cloud/pair-qr", "/api/status"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"):
            with self.subTest(method=method):
                self.assertEqual(self.request(method, "/api/diagnostics/v1")[0], 405)
        self.assertEqual(self.engine.forbidden_calls, [])

    def test_busy_state_is_explicitly_unavailable(self):
        self.engine.state_lock.acquire()
        try:
            status, _, body = self.request("GET", "/api/diagnostics/v1")
        finally:
            self.engine.state_lock.release()
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["reason"], "state_busy")

    def test_existing_socket_cannot_be_replaced(self):
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            diag.start_private_diagnostics_server(str(self.path), FakeEngine(), profile="lan")


class PathSafetyTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(socket, "AF_UNIX") and os.name == "posix", "Unix sockets required")
    def test_reject_world_readable_parent(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "open"
            p.mkdir(mode=0o755)
            with self.assertRaisesRegex(RuntimeError, "owner-only"):
                diag.start_private_diagnostics_server(str(p / "test.sock"),
                                                       FakeEngine(), profile="lan")
            self.assertFalse((p / "test.sock").exists())

    @unittest.skipUnless(hasattr(socket, "AF_UNIX") and os.name == "posix", "Unix sockets required")
    def test_reject_preexisting_symlink_without_deleting_target(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "private"
            p.mkdir(mode=0o700)
            victim = p / "victim"
            victim.write_text("unchanged", encoding="utf-8")
            sock = p / "test.sock"
            sock.symlink_to(victim)
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                diag.start_private_diagnostics_server(str(sock), FakeEngine(), profile="lan")
            self.assertEqual(victim.read_text(encoding="utf-8"), "unchanged")

    def test_dashboard_lan_handler_does_not_expose_diagnostic_path(self):
        # Existing dashboard GET routes must not be extended to diagnostic GET.
        from http.server import ThreadingHTTPServer
        from urllib.error import HTTPError
        from urllib.request import urlopen
        real_server = ThreadingHTTPServer(("127.0.0.1", 0), edge_dashboard.Handler)
        real_server.engine = FakeEngine()
        real_server.key = "not-the-diagnostics-key"
        thread = threading.Thread(target=real_server.serve_forever, daemon=True)
        thread.start()
        try:
            url = "http://127.0.0.1:%s/api/diagnostics/v1" % real_server.server_port
            with self.assertRaises(HTTPError) as exc:
                urlopen(url, timeout=2)
            self.assertEqual(exc.exception.code, 404)
        finally:
            real_server.shutdown()
            real_server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
