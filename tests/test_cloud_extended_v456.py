"""Extended cloud session tests, all mocked; no hardware or network requests."""
from datetime import datetime, timezone
import sys, time, unittest
import tempfile
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import edge_dashboard as m

class ExtendedCloudTests(unittest.TestCase):
    def setUp(self):
        self._temp_cloud_flag = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_cloud_flag.cleanup)
        self._cloud_flag_override = patch.object(m, 'HTTPS_ENABLE_FLAG', Path(self._temp_cloud_flag.name) / '.edge_https_cloud_enabled')
        self._cloud_flag_override.start()
        self.addCleanup(self._cloud_flag_override.stop)
        m.HTTPS_ENABLE_FLAG.touch(mode=0o600)
        self.e=m.HybridEngine('127.0.0.1', token='fake', uid='unused', simulate=False)
        self.e.https_cloud_enabled=True
        self.e._local_api=lambda p: (_ for _ in ()).throw(RuntimeError('No LAN'))
        self.calls=[]
        self.e._cloud_api=lambda p: self.calls.append(p.copy()) or {'code':200}
        self.age=2
        self.e._paired_status=lambda: {'uid':'pd-https-extended-test', 'age_seconds':self.age,
            'updated_utc':datetime.now(timezone.utc).isoformat()}
    def tearDown(self):
        self.e.shutdown()
    def test_one_minute_cloud_needs_no_extra_consent(self):
        s=self.e.start({'mode':'wave','minutes':1})
        self.assertTrue(s['running'])
    def test_five_minute_cloud_with_consent(self):
        s=self.e.start({'mode':'wave','minutes':5,'acceptExtendedCloudRisk':True})
        self.assertGreater(s['secondsLeft'],295)
        self.assertEqual(s['connectionMode'],'cloud')
    def test_120_minutes_cloud_with_consent(self):
        s=self.e.start({'mode':'wave','minutes':120,'acceptExtendedCloudRisk':True})
        self.assertGreater(s['secondsLeft'],7100)
    def test_until_stopped_cloud_with_consent(self):
        s=self.e.start({'mode':'autonomous','untilStopped':True,'acceptExtendedCloudRisk':True})
        self.assertTrue(s['untilStopped'])
        self.assertIsNone(s['secondsLeft'])
        self.assertEqual(self.e.end,float('inf'))
    def test_bad_confirmation_values_rejected(self):
        for val in (False,None,'true',1,0):
            with self.subTest(val=val):
                with self.assertRaisesRegex(RuntimeError,'requires confirming'):
                    self.e.start({'mode':'wave','minutes':15,'acceptExtendedCloudRisk':val})
    def test_cloud_preflight_cannot_be_bypassed_by_consent(self):
        self.age=120
        with self.assertRaisesRegex(RuntimeError,'older than 90s'):
            self.e.start({'mode':'wave','minutes':60,'acceptExtendedCloudRisk':True})
    def test_change_patterns_keeps_unlimited_cloud_running(self):
        self.e.start({'mode':'wave','untilStopped':True,'acceptExtendedCloudRisk':True})
        prev_end=self.e.end; started=self.e.started
        s=self.e.switch_pattern({'mode':'pulse'})
        self.assertTrue(s['running'])
        self.assertEqual(s['mode'],'pulse')
        self.assertEqual(self.e.started, started)
        self.assertEqual(self.e.end, prev_end)
    def test_long_cloud_watchdog_cancels_on_expired_callback(self):
        self.e.start({'mode':'wave','minutes':30,'acceptExtendedCloudRisk':True})
        self.age=91
        for _ in range(180):
            if self.e.status()['faultLatched']:
                break
            time.sleep(.025)
        s=self.e.status()
        self.assertFalse(s['running'])
        self.assertTrue(s['faultLatched'])
        self.assertTrue(s['cloudRequiresPhysicalOff'])
    def test_long_cloud_motor_command_refuses_stale_callback(self):
        self.e.start({'mode':'wave','minutes':30,'acceptExtendedCloudRisk':True})
        with self.e.state_lock:
            self.e.generation+=1
            generation=self.e.generation
        before=len(self.calls)
        self.age=91
        with self.assertRaisesRegex(RuntimeError,'pairing expired'):
            self.e._send_levels(generation,1,1)
        self.assertEqual(len(self.calls),before)
    def test_stop_after_long_cloud_keeps_lock(self):
        self.e.start({'mode':'wave','minutes':30,'acceptExtendedCloudRisk':True})
        self.e.stop('Finished')
        s=self.e.status()
        self.assertTrue(s['faultLatched'])
        with self.assertRaisesRegex(RuntimeError,'POWER OFF'):
            self.e.acknowledge_fault()
    def test_motor_payload_stays_short_bounded(self):
        self.e.start({'mode':'wave','untilStopped':True,'acceptExtendedCloudRisk':True})
        time.sleep(.04)
        for c in self.calls:
            if c.get('action','').startswith('Vibrate'):
                self.assertLessEqual(c.get('timeSec',99),2)

if __name__=='__main__': unittest.main()
