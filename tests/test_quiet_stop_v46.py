"""v4.6 quiet routine cloud Stop: fully mocked, NO device or external I/O."""
from datetime import datetime, timezone
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edge_dashboard as pd


class QuietStopTests(unittest.TestCase):
    def setUp(self):
        self.e = pd.HybridEngine('127.0.0.1', token='non-secret-test-token', uid='test-only', simulate=False)
        self.e._local_api = lambda p: (_ for _ in ()).throw(RuntimeError('mock LAN unavailable'))
        self.e.https_cloud_enabled = True
        self.calls = []
        self.e._cloud_api = lambda p: self.calls.append(p.copy()) or {'code': 200}
        self.e._paired_status = lambda: {
            'uid': 'test-pairing-only', 'age_seconds': 1,
            'updated_utc': datetime.now(timezone.utc).isoformat()}

    def tearDown(self):
        # No real Stop I/O: the mocked backend receives all command attempts.
        self.e.shutdown()

    def start_cloud(self):
        result = self.e.start({'mode':'wave','max':2,'minutes':.25})
        self.assertEqual(result['connectionMode'], 'cloud')

    def test_manual_stop_is_quiet_but_backend_cannot_restart_without_confirmation(self):
        self.start_cloud()
        status = self.e.stop('Stopped')
        self.assertFalse(status['running'])
        self.assertTrue(status['cloudRoutineStopConfirmRequired'])
        self.assertTrue(status['faultLatched'])
        self.assertFalse(status['stopPending'])
        self.assertFalse(status['physicalStopVerified'])
        with self.assertRaisesRegex(RuntimeError, 'locked'):
            self.start_cloud()
        with self.assertRaisesRegex(RuntimeError, 'PHYSICAL POWER OFF'):
            self.e.acknowledge_fault(physical_off=False)
        status = self.e.acknowledge_fault(physical_off=True)
        self.assertFalse(status['cloudRoutineStopConfirmRequired'])
        self.assertFalse(status['faultLatched'])

    def test_deadline_expiry_creates_routine_state_not_connection_error(self):
        self.start_cloud()
        with self.e.state_lock:
            self.e.end = time.monotonic() - .1
        self.e.wake.set()
        for _ in range(100):
            if not self.e.status()['running']:
                break
            time.sleep(.02)
        s = self.e.status()
        self.assertFalse(s['running'])
        self.assertTrue(s['cloudRoutineStopConfirmRequired'])
        self.assertIn('Session finished', s['message'])

    def test_explicit_connection_fault_is_immediately_alertable(self):
        self.start_cloud()
        s = self.e.stop('Cloud connection lost', fault=True)
        self.assertTrue(s['faultLatched'])
        self.assertTrue(s['stopPending'])
        self.assertFalse(s['cloudRoutineStopConfirmRequired'])

    def test_failed_cloud_stop_never_masquerades_as_routine(self):
        self.start_cloud()
        self.e._cloud_api = lambda p: (_ for _ in ()).throw(RuntimeError('mock cloud stop failed'))
        with self.assertRaisesRegex(RuntimeError, 'mock cloud stop failed'):
            self.e.stop('Stopped')
        s = self.e.status()
        self.assertTrue(s['faultLatched'])
        self.assertTrue(s['stopPending'])
        self.assertFalse(s['cloudRoutineStopConfirmRequired'])

    def test_lan_stop_never_requires_cloud_confirmation(self):
        e = pd.Engine('127.0.0.1', simulate=True)
        try:
            e.start({'mode':'wave','minutes':1})
            s = e.stop('Stopped')
            self.assertFalse(s['faultLatched'])
            self.assertFalse(e.routine_cloud_stop_confirm_required)
        finally:
            e.shutdown()

    def test_genuine_failure_after_quiet_stop_overrides_routine_flag(self):
        self.start_cloud()
        self.e.stop('Stopped')
        self.assertTrue(self.e.status()['cloudRoutineStopConfirmRequired'])
        self.e._cloud_api = lambda p: (_ for _ in ()).throw(RuntimeError('new fault'))
        with self.assertRaises(RuntimeError):
            self.e.stop('Failed idle stop')
        s = self.e.status()
        self.assertFalse(s['cloudRoutineStopConfirmRequired'])
        self.assertTrue(s['stopPending'])


if __name__ == '__main__':
    unittest.main()
