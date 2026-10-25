"""Offline API and physical-control safety regressions for the LAN-only candidate.

All tests use simulation or patched local API responses; they never contact a device.
"""
import json
import io
import pathlib
import sys
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import edge_dashboard as dashboard


class DeviceValidationRegressions(unittest.TestCase):
    @staticmethod
    def toys_response(toys):
        return {"code": 200, "data": {"toys": json.dumps(toys)}}

    def test_string_wrapped_device_data_is_accepted(self):
        nested = json.dumps({"toys": json.dumps({"e": {"name": "Edge 2", "status": "1"}})})
        item = dashboard.Engine._extract_toy({"data": nested})
        self.assertIsNotNone(item)

    def test_multiple_connected_edges_are_rejected(self):
        item = dashboard.Engine._extract_toy(self.toys_response({
            "a": {"name": "Edge 2", "status": "1"},
            "b": {"name": "Edge 2", "status": "1"},
        }))
        self.assertIsNone(item)

    def test_start_does_not_send_motor_command_for_max_2(self):
        engine = dashboard.Engine("127.0.0.1", simulate=False)
        sent = []
        def fake_api(payload):
            sent.append(payload)
            if payload.get("command") == "GetToys":
                return self.toys_response({"max": {"name": "Max 2", "status": "1"}})
            return {"code": 200}
        try:
            with patch.object(engine, "_api", side_effect=fake_api):
                with self.assertRaisesRegex(RuntimeError, "not confirmed"):
                    engine.start({"mode": "wave"})
                self.assertEqual(engine.status()["mode"], "idle")
                self.assertFalse(any(x.get("command") == "Function" for x in sent))
        finally:
            with patch.object(engine, "_api", return_value={"code": 200}):
                engine.shutdown()


class StopAndAccessRegressions(unittest.TestCase):
    def setUp(self):
        self.engine = dashboard.Engine("127.0.0.1", simulate=True)

    def tearDown(self):
        self.engine.shutdown()

    def test_stop_invalidates_old_generation_commands(self):
        self.engine.start({"mode": "manual", "max": 5, "motor1": 5, "motor2": 5})
        with self.engine.state_lock:
            old_generation = self.engine.generation
        self.engine.stop()
        with patch.object(self.engine, "_api") as api:
            accepted = self.engine._send_levels(old_generation, 5, 5)
        self.assertFalse(accepted)
        api.assert_not_called()
        self.assertEqual(self.engine.status()["mode"], "idle")

    def test_stop_attempt_failure_keeps_session_idle(self):
        self.engine.start({"mode": "wave"})
        with patch.object(self.engine, "_send_stop", side_effect=RuntimeError("simulated disconnect")):
            with self.assertRaises(RuntimeError):
                self.engine.stop()
        self.assertFalse(self.engine.status()["running"])
        self.assertIn("STOP NOT DELIVERED", self.engine.status()["message"])
        self.assertTrue(self.engine.status()["faultLatched"])

    def test_expired_generation_cannot_send_levels(self):
        self.engine.start({"mode": "manual", "max": 5, "motor1": 5, "motor2": 5})
        with self.engine.state_lock:
            gen = self.engine.generation
            self.engine.end = time.monotonic() - 1
        with patch.object(self.engine, "_api") as api:
            accepted = self.engine._send_levels(gen, 5, 5)
        self.assertFalse(accepted)
        api.assert_not_called()


class MalformedApiResponseRegressions(unittest.TestCase):
    def test_non_object_json_is_a_recoverable_runtime_error(self):
        # The API parser should never raise AttributeError on valid JSON that
        # isn't a response object: workers must get RuntimeError and fail closed.
        engine = object.__new__(dashboard.Engine)
        engine.simulate = False
        engine.url = "http://127.0.0.1:20010/command"
        for payload in (b"[]", b'"unexpected"', b"null"):
            with self.subTest(payload=payload):
                with patch.object(dashboard, "urlopen", return_value=io.BytesIO(payload)):
                    with self.assertRaisesRegex(RuntimeError, "unexpected response"):
                        engine._api({"command": "GetToys"})


class HTTPAccessRegressions(unittest.TestCase):
    def setUp(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        self.engine = dashboard.Engine("127.0.0.1", simulate=True)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        self.server.engine, self.server.key = self.engine, "integration-key-only-for-tests"
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.engine.shutdown()

    def test_mutating_endpoints_require_access_key(self):
        for path in ("/api/start", "/api/stop", "/api/test"):
            with self.subTest(path=path):
                req = Request(self.base + path, data=b"{}", headers={"Content-Type": "application/json"})
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(req, timeout=3)
                self.assertEqual(ctx.exception.code, 401)
        self.assertFalse(self.engine.status()["running"])

    def test_browser_security_headers(self):
        with urlopen(self.base + "/", timeout=3) as response:
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")
            self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertIn("frame-ancestors 'none'", response.headers.get("Content-Security-Policy", ""))


if __name__ == "__main__":
    unittest.main()