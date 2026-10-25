"""Offline regression checks. No Lovense hardware or networking required."""
import importlib
import json
import os
import pathlib
import random
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import edge_dashboard as dashboard
from edge2_director import AutonomousDirector, STYLES, FLOWS


class DirectorTests(unittest.TestCase):
    def test_defaults(self):
        director = AutonomousDirector()
        self.assertEqual((director.style, director.flow, director.surprise), ("confident", "driving", 4))

    def test_all_behaviours_are_bounded(self):
        for style in STYLES:
            for flow in FLOWS:
                with self.subTest(style=style, flow=flow):
                    d = AutonomousDirector(style=style, flow=flow, rng=random.Random(37))
                    for t in range(0, 1800, 4):
                        a, b = d.levels(t, 13, 5, 65, 1800)
                        self.assertTrue(0 <= a <= 13)
                        self.assertTrue(0 <= b <= 13)
                    self.assertGreater(d.decision_count, 0)

    def test_second_motor_support_zero(self):
        d = AutonomousDirector(rng=random.Random(22))
        for t in range(0, 300, 3):
            _, b = d.levels(t, 15, 3, 0, 300)
            self.assertEqual(b, 0)


class ConnectionSelectionTests(unittest.TestCase):
    @staticmethod
    def response(toys):
        return {"data": {"toys": json.dumps(toys)}}

    def test_single_edge2_is_allowed(self):
        for name in ("Edge", "Edge 2", "EDGE2"):
            toy = dashboard.Engine._extract_toy(self.response({"id": {"name": name, "status": 1}}))
            self.assertIsNotNone(toy)


    def test_max2_is_rejected(self):
        toy = dashboard.Engine._extract_toy(self.response({"id": {"name": "Max 2", "status": 1}}))
        self.assertIsNone(toy)

    def test_multiple_connected_devices_refused(self):
        toy = dashboard.Engine._extract_toy(self.response({"a": {"name": "Edge", "status": 1}, "b": {"name": "Max 2", "status": 1}}))
        self.assertIsNone(toy)

    def test_disconnected_or_unknown_is_refused(self):
        for toys in ({"a": {"name": "Edge", "status": 0}}, {"a": {"nickName": "Edge", "status": 1}}, {}):
            toy = dashboard.Engine._extract_toy(self.response(toys))
            self.assertIsNone(toy)

    def test_start_refused_if_unverified(self):
        engine = dashboard.Engine("127.0.0.1", simulate=True)
        try:
            with patch.object(engine, "refresh_toys", return_value={"toyConnected": False, "lastDeviceError": "Incorrect toy"}):
                with self.assertRaises(RuntimeError):
                    engine.start({"mode": "wave"})
            self.assertEqual(engine.status()["mode"], "idle")
        finally:
            engine.shutdown()


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = dashboard.Engine("127.0.0.1", simulate=True)

    def tearDown(self):
        self.engine.shutdown()

    def test_autonomous_start_and_stop(self):
        started = self.engine.start({"mode": "autonomous", "max": 13, "surprise": 4, "style": "confident", "flow": "driving"})
        self.assertEqual(started["directorStyle"], "confident")
        self.assertEqual(started["directorFlow"], "driving")
        self.assertTrue(started["running"])
        self.assertLessEqual(started["secondsLeft"], 300)
        self.engine.stop()
        self.assertFalse(self.engine.status()["running"])

    def test_invalid_settings_do_not_start(self):
        for invalid in (float("nan"), float("inf"), "banana"):
            with self.assertRaises(ValueError):
                self.engine.start({"max": invalid})
        self.assertFalse(self.engine.status()["running"])

    def test_motors_obey_maximum(self):
        status = self.engine.start({"mode": "manual", "max": 7, "motor1": 20, "motor2": 18, "minutes": .25})
        self.assertEqual(status["max"], 7)
        self.assertEqual(self.engine.motor1, 7)
        self.assertEqual(self.engine.motor2, 7)

    def test_simulation_telemetry(self):
        s = self.engine.refresh_toys()
        self.assertTrue(s["toyConnected"])
        self.assertEqual(s["battery"], 72)
        self.assertEqual(s["deviceName"], "Edge 2")

    def test_automatic_expiry_stops(self):
        self.engine.start({"mode": "wave", "minutes": .25})
        with self.engine.state_lock:
            self.engine.end = time.monotonic() + .08
            self.engine.wake.set()
        deadline = time.monotonic() + 2
        while self.engine.status()["running"] and time.monotonic() < deadline:
            time.sleep(.025)
        self.assertFalse(self.engine.status()["running"])
        self.assertEqual(self.engine.status()["motor1"], 0)
        self.assertEqual(self.engine.status()["motor2"], 0)


    def test_pattern_bounds(self):
        for mode in dashboard.RANDOM_MODES:
            for t in range(0, 40, 3):
                a, b = self.engine._pattern(mode, t, 10, 3, 4, 4, [], 65)
                self.assertTrue(0 <= a <= 10 and 0 <= b <= 10)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.engine = dashboard.Engine("127.0.0.1", simulate=True)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        self.server.engine, self.server.key = self.engine, "test-key-0123456789"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.engine.shutdown()

    def request(self, path, data=None, key=True):
        headers = {"X-Edge-Key": self.server.key} if key else {}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = Request(self.url + path,
                      data=json.dumps(data).encode("utf8") if data is not None else None,
                      headers=headers)
        with urlopen(req, timeout=3) as response:
            return response.status, response.read().decode()

    def test_dashboard_served(self):
        status, html = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("Autonomous Director", html)
        self.assertNotIn("Cloud Keeper", html)

    def test_unauthorized_status_denied(self):
        with self.assertRaises(HTTPError) as ctx:
            self.request("/api/status", key=False)
        self.assertEqual(ctx.exception.code, 401)

    def test_start_status_stop(self):
        status, result = self.request("/api/start", {"mode": "autonomous"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(result)["running"])
        _, result = self.request("/api/status")
        self.assertEqual(json.loads(result)["directorStyle"], "confident")
        status, result = self.request("/api/stop", {})
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(result)["running"])

    def test_invalid_payload_denied(self):
        with self.assertRaises(HTTPError) as ctx:
            self.request("/api/start", {"mode": "not-a-mode"})
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
