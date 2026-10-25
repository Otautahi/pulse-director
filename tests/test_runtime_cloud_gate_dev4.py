"""Dev4 runtime gate tests: fake cloud transport, zero hardware/network I/O."""
import os, sys, tempfile, time, unittest
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import edge_dashboard as d

class Dev4CloudRevocation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.flag=Path(self.tmp.name)/'.edge_https_cloud_enabled'
        self.flag.touch(mode=0o600)
        self.p=patch.object(d,'HTTPS_ENABLE_FLAG',self.flag)
        self.p.start()
        self.addCleanup(self.p.stop)
        self.e=d.HybridEngine('127.0.0.1',token='DUMMY-OFFLINE',uid='none',simulate=False)
        self.e._local_api=lambda p: (_ for _ in ()).throw(RuntimeError('fake LAN unavailable'))
        self.e._paired_status=lambda: {'uid':'pd-test-only',
              'age_seconds':2,'updated_utc':datetime.now(timezone.utc).isoformat()}
        self.e._cloud_api=lambda p: {'code':200}   # Always intercepted except direct-transport test.
        self.addCleanup(self.e.shutdown)
        self.assertTrue(self.e.https_cloud_enabled)

    def test_removal_immediately_revokes_readiness(self):
        self.assertTrue(self.e._cloud_start_readiness(self.e._keeper_snapshot())[0])
        self.flag.unlink()
        self.assertFalse(self.e._cloud_start_readiness(self.e._keeper_snapshot())[0])
        self.assertFalse(self.e.status()['cloudExperimentalEnabled'])
        self.assertFalse(self.e.status()['cloudCanStart'])
        with self.assertRaisesRegex(RuntimeError,'disabled|revoked'):
            self.e.start({'mode':'motor1','max':1,'minutes':0.25})

    def test_recreated_flag_cannot_rearm_running_process(self):
        self.flag.unlink()
        self.assertFalse(self.e._cloud_enabled_now())
        self.flag.touch(mode=0o600)
        self.assertFalse(self.e._cloud_enabled_now())

    def test_symlink_and_world_readable_flag_cannot_enable(self):
        self.flag.unlink()
        fake_target=Path(self.tmp.name)/'target'
        fake_target.touch(mode=0o600)
        self.flag.symlink_to(fake_target)
        self.assertFalse(self.e._cloud_enabled_now())
        self.flag.unlink()
        self.flag.touch(mode=0o600)
        self.flag.chmod(0o644)  # umask 077 must not mask the insecure test case
        another=d.HybridEngine('127.0.0.1',token='DUMMY-OFFLINE',uid='none',simulate=True)
        try:
            self.assertFalse(another.https_cloud_enabled)
        finally:
            another.shutdown()

    def test_preflight_flag_removal_blocks_cloud_start(self):
        def preflight():
            self.flag.unlink()
            return {'code':200}
        self.e._cloud_stop_preflight=preflight
        with self.assertRaisesRegex(RuntimeError,'revoked'):
            self.e.start({'mode':'motor1','max':1,'minutes':0.25})
        self.assertFalse(self.e.status()['running'])

    def test_runtime_removal_latches_active_session_without_replay(self):
        calls=[]
        self.e._cloud_api=lambda p: calls.append(p.copy()) or {'code':200}
        result=self.e.start({'mode':'motor1','max':1,'minutes':0.5})
        self.assertTrue(result['running'])
        self.flag.unlink()
        # Independently trigger the gate immediately; heartbeat thread later detects it.
        self.assertFalse(self.e._cloud_enabled_now())
        end=time.monotonic()+6
        while not self.e.status()['faultLatched'] and time.monotonic()<end:
            time.sleep(.05)
        s=self.e.status()
        self.assertFalse(s['running'])
        self.assertTrue(s['faultLatched'])
        self.assertTrue(s['cloudRequiresPhysicalOff'])
        self.assertFalse(s['cloudExperimentalEnabled'])
        before=len([x for x in calls if str(x.get('action','')).startswith('Vibrate')])
        time.sleep(0.25)
        self.assertEqual(before,len([x for x in calls if str(x.get('action','')).startswith('Vibrate')]))
        with self.assertRaises(RuntimeError):
            self.e.start({'mode':'motor1','max':1,'minutes':0.25})

    def test_real_transport_never_sends_motor_after_revocation_but_stop_allowed(self):
        # Calls subprocess.run only through a patched fake -- no curl execution.
        self.e.cloud_session_uid='pd-test-only'
        self.flag.unlink()
        calls=[]
        def fake_run(cmd, **kwargs):
            calls.append(kwargs['input'])
            return SimpleNamespace(returncode=0,stdout='{"code":200}\nHTTP_STATUS:200')
        del self.e.__dict__['_cloud_api'] # exercise real transport implementation
        with patch.object(d.subprocess,'run',side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError,'revoked'):
                self.e._cloud_api({'command':'Function','action':'Vibrate1:1,Vibrate2:0','timeSec':2})
            self.assertEqual(calls,[])
            result=self.e._cloud_api({'command':'Function','action':'Stop','timeSec':0,'stopPrevious':1})
            self.assertEqual(result['code'],200)
            self.assertEqual(len(calls),1)
            self.assertIn('"action": "Stop"',calls[0])

if __name__=='__main__': unittest.main()
