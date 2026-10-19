"""v4.6 unified LAN/hybrid profiles: no hardware or external network I/O."""
import io
import pathlib
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import edge_dashboard as pd


class UnifiedProfilesTests(unittest.TestCase):
    def test_create_lan_profile(self):
        e = pd.build_engine("lan", "127.0.0.1", token="ignored", simulate=True)
        try:
            self.assertIs(type(e), pd.Engine)
            self.assertEqual(e.status()["profile"], "lan")
            self.assertTrue(e.status()["simulated"])
            self.assertTrue(e.status()["running"] is False)
        finally:
            e.shutdown()

    def test_create_hybrid_profile(self):
        e = pd.build_engine("hybrid", "127.0.0.1", simulate=True)
        try:
            self.assertIs(type(e), pd.HybridEngine)
            self.assertEqual(e.status()["profile"], "hybrid")
            self.assertEqual(e.status()["connectionMode"], "simulation")
        finally:
            e.shutdown()

    def test_unknown_profile_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            pd.build_engine("cloud-only", "127.0.0.1", simulate=True)

    def test_lan_profile_stop_is_quiet(self):
        e = pd.build_engine("lan", "127.0.0.1", simulate=True)
        try:
            e.start({"mode": "autonomous", "minutes": .5})
            s = e.stop("Stopped by owner")
            self.assertFalse(s["running"])
            self.assertFalse(s["faultLatched"])
            self.assertEqual(s["profile"], "lan")
        finally:
            e.shutdown()

    def test_lan_profile_refuses_cloud_pairing_endpoint(self):
        e = pd.build_engine("lan", "127.0.0.1", simulate=True)
        try:
            dummy = pd.Handler.__new__(pd.Handler)
            dummy.headers = {"X-Edge-Key": "only-test-key", "Content-Length": "2"}
            dummy.server = SimpleNamespace(key="only-test-key", engine=e, pair_qr=SimpleNamespace(generate=lambda eng: self.fail("Cloud must not run")))
            dummy.path = "/api/cloud/pair-qr"
            dummy.rfile = io.BytesIO(b"{}")
            replies = []
            dummy._json = lambda code, data: replies.append((code, data))
            dummy.do_POST()
            self.assertEqual(replies[0][0], 404)
        finally:
            e.shutdown()

    def test_lan_profile_denies_unauthorized_pairing(self):
        e = pd.build_engine("lan", "127.0.0.1", simulate=True)
        try:
            dummy = pd.Handler.__new__(pd.Handler)
            dummy.headers = {"X-Edge-Key": "wrong", "Content-Length": "2"}
            dummy.server = SimpleNamespace(key="only-test-key", engine=e)
            dummy.path = "/api/cloud/pair-qr"
            dummy.rfile = io.BytesIO(b"{}")
            replies = []
            dummy._json = lambda code, data: replies.append((code, data))
            dummy.do_POST()
            self.assertEqual(replies[0][0], 401)
        finally:
            e.shutdown()

    def test_lan_cloud_environment_has_no_cloud_fields(self):
        e = pd.build_engine("lan", "127.0.0.1", simulate=True)
        try:
            state = e.status()
            self.assertNotIn("cloudCanStart", state)
            self.assertNotIn("cloudPairingConfirmed", state)
        finally:
            e.shutdown()

    def test_hybrid_profile_simulated_stop_is_quiet(self):
        e = pd.build_engine("hybrid", "127.0.0.1", simulate=True)
        try:
            e.start({"mode": "wave", "minutes": .25})
            state = e.stop("Stopped by owner")
            self.assertFalse(state["running"])
            self.assertFalse(state["cloudRoutineStopConfirmRequired"])
        finally:
            e.shutdown()

    def test_default_phone_is_localhost_not_someones_lan(self):
        self.assertEqual(pd.DEFAULT_PHONE, "127.0.0.1")

    def test_html_hides_cloud_panel_in_lan_profile(self):
        self.assertIn('if(s.profile === "lan")', pd.HTML)
        self.assertIn('$("pairingPanel").classList.add("hide")', pd.HTML)

    def test_lan_profile_motor_levels_never_exceed_cap(self):
        e = pd.build_engine("lan", "127.0.0.1", simulate=True)
        try:
            e.start({"mode": "autonomous", "max": 7})
            gen = e.generation
            self.assertTrue(e._send_levels(gen, 7, 7))
            self.assertEqual(e.status()["max"], 7)
            e.stop()
            self.assertFalse(e._send_levels(gen, 7, 7))
        finally:
            e.shutdown()

    def test_trusted_callback_token_path_is_project_relative(self):
        import importlib.util
        path = ROOT / "https-standard-probe" / "https_probe.py"
        spec = importlib.util.spec_from_file_location("pd_probe_testonly", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.DEFAULT_TOKEN_FILE, path.parent.parent / ".edge_cloud_token")


if __name__ == "__main__":
    unittest.main()
