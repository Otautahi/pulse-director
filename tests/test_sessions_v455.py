"""Offline session-extension tests; never send network or device commands."""
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path
from datetime import datetime, timezone, timedelta
import threading
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import edge_dashboard as m


class LANSessionTests(unittest.TestCase):
    def setUp(self):
        self.engine=m.Engine('127.0.0.1',simulate=True)
    def tearDown(self):
        self.engine.shutdown()
    def test_unlimited_session_has_no_deadline_or_infinite_json(self):
        s=self.engine.start({'mode':'wave','minutes':5,'untilStopped':True})
        self.assertTrue(s['running']);self.assertTrue(s['untilStopped'])
        self.assertIsNone(s['secondsLeft']);self.assertEqual(s['sessionProgress'],0)
        self.assertEqual(self.engine.end,float('inf'))
    def test_explicit_stop_ends_unlimited_session(self):
        self.engine.start({'mode':'wave','untilStopped':True})
        s=self.engine.stop()
        self.assertFalse(s['running']);self.assertFalse(s['untilStopped'])
    def test_120_minute_session_allowed(self):
        s=self.engine.start({'mode':'wave','minutes':120})
        self.assertTrue(7190 < s['secondsLeft'] <= 7200)
        self.assertFalse(s['untilStopped'])
    def test_pattern_switch_keeps_timer_and_route_and_counters(self):
        self.engine.active_route='lan'
        self.engine.start({'mode':'wave','minutes':15})
        with self.engine.state_lock:
            original_end=self.engine.end
            original_start=self.engine.started
            self.engine.session_commands=5
        s=self.engine.switch_pattern({'mode':'pulse','max':3})
        self.assertEqual(s['mode'],'pulse')
        self.assertTrue(s['running'])
        self.assertEqual(original_end,self.engine.end)
        self.assertEqual(original_start,self.engine.started)
        self.assertEqual(self.engine.active_route,'lan')
        self.assertGreaterEqual(s['sessionCommands'],5)
    def test_switch_to_director_during_unlimited_preserves_deadline(self):
        self.engine.start({'mode':'wave','untilStopped':True})
        s=self.engine.switch_pattern({'mode':'autonomous','style':'confident','surprise':4,'flow':'driving'})
        self.assertEqual(s['mode'],'autonomous')
        self.assertEqual(self.engine.end,float('inf'))
        self.assertTrue(s['untilStopped'])
        self.assertIsNotNone(self.engine.director)
    def test_switch_without_session_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'No safe active session'):
            self.engine.switch_pattern({'mode':'wave'})
    def test_stop_blocks_switch(self):
        self.engine.start({'mode':'wave','minutes':2})
        self.engine.stop()
        with self.assertRaisesRegex(RuntimeError,'No safe active session'):
            self.engine.switch_pattern({'mode':'pulse'})
    def test_invalid_unlimited_value_rejected(self):
        with self.assertRaisesRegex(ValueError,'unlimited timer flag'):
            self.engine.start({'mode':'wave','untilStopped':'true'})
    def test_motor_test_resets_unlimited_status(self):
        self.engine.start({'mode':'wave','untilStopped':True})
        self.engine.stop()
        s=self.engine.test()
        self.assertFalse(s['untilStopped'])
        self.assertIsInstance(s['secondsLeft'],int)


class CloudSessionTests(unittest.TestCase):
    def setUp(self):
        self._temp_cloud_flag = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_cloud_flag.cleanup)
        self._cloud_flag_override = patch.object(m, 'HTTPS_ENABLE_FLAG', Path(self._temp_cloud_flag.name) / '.edge_https_cloud_enabled')
        self._cloud_flag_override.start()
        self.addCleanup(self._cloud_flag_override.stop)
        m.HTTPS_ENABLE_FLAG.touch(mode=0o600)
        self.e=m.HybridEngine('127.0.0.1',token='not-real-token',uid='old',simulate=False)
        self.e._local_api=lambda p: (_ for _ in ()).throw(RuntimeError('LAN unavailable'))
        self.sent=[]
        self.e._cloud_api=lambda p: self.sent.append(p) or {'code':200}
        self.e.https_cloud_enabled=True
        self.age=1
        self.e._paired_status=lambda:{'uid':'pd-https-offline-test','age_seconds':self.age,'updated_utc':datetime.now(timezone.utc).isoformat()}
    def tearDown(self):
        self.e.shutdown()
    def test_cloud_unlimited_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(RuntimeError,'requires confirming'):
            self.e.start({'mode':'wave','minutes':.5,'untilStopped':True})
        self.assertFalse(self.e.status()['running'])
    def test_cloud_two_minutes_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(RuntimeError,'requires confirming'):
            self.e.start({'mode':'wave','minutes':2})
        self.assertFalse(self.e.status()['running'])
    def test_cloud_switch_does_not_stop_or_rearm(self):
        self.e.start({'mode':'wave','minutes':.5})
        # Background cloud motor worker may send a normal Vibrate update at
        # any time during an active session. Only STOP/preflight calls must
        # remain unchanged when switching patterns; total calls need not.
        stops_before=sum(p.get('action') == 'Stop' for p in self.sent)
        self.assertGreaterEqual(stops_before, 1)  # initial STOP-only preflight
        before_end=self.e.end
        before_start=self.e.started
        before_route=self.e.active_route
        before_uid=self.e.cloud_session_uid
        s=self.e.start({'mode':'pulse','minutes':120,'untilStopped':True})
        self.assertEqual(s['mode'],'pulse')
        self.assertEqual(before_end,self.e.end)
        self.assertEqual(before_start,self.e.started)
        self.assertEqual(before_route,self.e.active_route)
        self.assertEqual(before_uid,self.e.cloud_session_uid)
        self.assertFalse(s['faultLatched'])
        self.assertEqual(stops_before, sum(p.get('action') == 'Stop' for p in self.sent))
        self.assertFalse(s['untilStopped'])
    def test_cloud_switch_stale_callback_fails_closed(self):
        self.e.start({'mode':'wave','minutes':.5})
        self.age=100
        with self.assertRaisesRegex(RuntimeError,'pairing unavailable'):
            self.e.switch_pattern({'mode':'pulse'})
        self.assertFalse(self.e.status()['running'])
        self.assertTrue(self.e.status()['faultLatched'])

class UIIntegrationTests(unittest.TestCase):
    def test_session_controls_and_separate_switch_route(self):
        src=(Path(__file__).resolve().parents[1]/'edge_dashboard.py').read_text()
        for string in ("'/api/switch'", 'id="untilStopped"','data-duration="120"','until you press Stop',
                       'a cloud connection interruption may prevent physical Stop'):
            self.assertIn(string,src)

if __name__ == '__main__':unittest.main()
