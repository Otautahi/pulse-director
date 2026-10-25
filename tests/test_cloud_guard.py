"""Cloud safety rules: entirely mocked, NO internet, toy, Bluetooth, or motor I/O."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import unittest
import time
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import edge_dashboard as m

class NoHardwareCloudGuard(unittest.TestCase):
    def setUp(self):
        self._temp_cloud_flag = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_cloud_flag.cleanup)
        self._cloud_flag_override = patch.object(m, 'HTTPS_ENABLE_FLAG', Path(self._temp_cloud_flag.name) / '.edge_https_cloud_enabled')
        self._cloud_flag_override.start()
        self.addCleanup(self._cloud_flag_override.stop)
        m.HTTPS_ENABLE_FLAG.touch(mode=0o600)
        self.engine=m.HybridEngine('127.0.0.1',token='fake-token',uid='old-uid',simulate=False)
        self.engine._local_api=lambda x:(_ for _ in ()).throw(RuntimeError('mock no LAN'))
        self.calls=[]
        self.engine._cloud_api=lambda p:self.calls.append(p.copy()) or {'code':200}
        self.engine.https_cloud_enabled=True
        self.age=2
        self.event_offset=-2
        self.engine._paired_status=self.paired
    def paired(self):
        return {'uid':'pd-https-cloud-test','age_seconds':self.age,
                'updated_utc':(datetime.now(timezone.utc)+timedelta(seconds=self.event_offset)).isoformat()}
    def tearDown(self):
        self.engine.shutdown()
    def start_cloud(self):
        return self.engine.start({'mode':'wave','max':2,'minutes':0.5})
    def test_older_than_policy_not_allowed_to_start(self):
        self.age=100
        with self.assertRaisesRegex(RuntimeError,'older than 90s'):self.start_cloud()
        self.assertFalse(self.engine.status()['running'])
    def test_accepted_server_stop_does_not_clear_safety_lock(self):
        self.start_cloud()
        self.engine.stop('User Stop')
        s=self.engine.status()
        self.assertFalse(s['running']);self.assertTrue(s['faultLatched'])
        self.assertTrue(s['cloudRequiresPhysicalOff']);self.assertFalse(s['stopPending'])
        self.assertFalse(s['physicalStopVerified'])
        self.assertIn('cloud Stop accepted by server',s['message'])
        self.assertTrue(s['cloudRoutineStopConfirmRequired'])
    def test_server_200_offline_is_not_proof_of_stop(self):
        self.start_cloud()
        # Fake API always returns 200, regardless of real app/device state.
        self.age=35
        self.engine.stop('Stop')
        with self.assertRaisesRegex(RuntimeError,'POWER OFF'):
            self.engine.acknowledge_fault()
        with self.assertRaisesRegex(RuntimeError,'POWER OFF'):
            self.engine.acknowledge_fault(physical_off='true')
    def test_explicit_physical_power_off_can_reset_cloud_fault(self):
        self.start_cloud();self.engine.stop('Manual')
        self.engine.acknowledge_fault(physical_off=True)
        s=self.engine.status();self.assertFalse(s['faultLatched'])
        self.assertFalse(s['stopPending']);self.assertFalse(s['running'])
    def test_lan_fault_does_not_require_cloud_off_confirmation(self):
        e=m.Engine('127.0.0.1',simulate=True)
        try:
            e.stop('Fault',fault=True)
            e._recovery_ready=lambda x:True
            e.stop_pending=False
            e.acknowledge_fault()
            self.assertFalse(e.status()['faultLatched'])
        finally:e.shutdown()
    def test_cloud_long_session_requires_explicit_consent(self):
        with self.assertRaisesRegex(RuntimeError,'requires confirming'):
            self.engine.start({'mode':'wave','minutes':2})
        self.assertFalse(self.engine.status()['running'])
    def test_cloud_motor_levels_refuse_stale_callback(self):
        self.start_cloud()
        with self.engine.io_lock:
            with self.engine.state_lock:
                self.engine.generation += 1 # isolate from worker race
                gen=self.engine.generation
            self.age=180
            before=sum(c.get('action','').startswith('Vibrate') for c in self.calls)
        with self.assertRaisesRegex(RuntimeError,'pairing expired'):
            self.engine._send_levels(gen,1,1)
        self.assertEqual(before,sum(c.get('action','').startswith('Vibrate') for c in self.calls))
    def test_cloud_recovery_refuses_old_pre_fault_callback(self):
        self.start_cloud()
        self.engine.stop('Fault',fault=True)
        self.assertTrue(self.engine.status()['stopPending'])
        self.assertFalse(self.engine._recovery_ready('cloud'))
    def test_cloud_recovery_after_fresh_event_ack_still_locks(self):
        self.start_cloud()
        self.engine.stop('Fault',fault=True)
        self.event_offset=2;self.age=0
        self.assertTrue(self.engine._recovery_ready('cloud'))
        self.engine.recovery_wake.set()
        for _ in range(120):
            if self.engine.status()['stopAcks']>=3:break
            time.sleep(0.025)
        s=self.engine.status()
        self.assertEqual(s['stopAcks'],3)
        self.assertTrue(s['stopPending'])
        self.assertTrue(s['faultLatched'])
        self.engine.acknowledge_fault(physical_off=True)
        self.assertFalse(self.engine.status()['faultLatched'])
    def test_dashboard_has_off_checkbox_and_explicit_api_parameter(self):
        self.assertIn('id="cloudOffConfirm"',m.HTML)
        self.assertIn('physicalOffConfirmed',m.HTML)
        self.assertIn('physicalOffConfirmed',Path(m.__file__).read_text())
    def test_idle_cloud_failed_stop_can_retry_after_new_callback(self):
        self.start_cloud();self.engine.stop('First STOP')
        self.engine.acknowledge_fault(physical_off=True)
        # Route stays pinned to cloud while idle; a failed Stop must still
        # record fault time so a subsequent callback can allow retry.
        def failed_stop(payload):
            raise RuntimeError('mock cloud HTTP unavailable')
        self.engine._cloud_api=failed_stop
        with self.assertRaisesRegex(RuntimeError,'mock cloud'):
            self.engine.stop('Stop again')
        self.assertTrue(self.engine.status()['stopPending'])
        self.assertFalse(self.engine._recovery_ready('cloud'))
        self.event_offset=2;self.age=0
        self.assertTrue(self.engine._recovery_ready('cloud'))
        self.engine.acknowledge_fault(physical_off=True)

    def test_cloud_stop_from_start_race_does_not_restart(self):
        self.start_cloud()
        self.engine.stop('manual')
        with self.assertRaises(RuntimeError):self.start_cloud()
        self.assertTrue(self.engine.status()['cloudRequiresPhysicalOff'])

if __name__=='__main__':unittest.main()
