"""Network-free HTTPS pairing/router tests. No motor or API I/O is permitted."""
import json
import pathlib
import sys
import tempfile
import os
import threading
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import edge2_https_pairing as pair
import edge_dashboard as dash

class PairTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.base=pathlib.Path(self.t.name)
        self.cfg={'uid':'pd-https-offline-unit','utoken':'x'*40}
        self.state={'state':'https_pairing_confirmed','edge2_connected':True,
                    'connected_device_count':1,
                    'updated_utc':datetime.now(timezone.utc).isoformat()}
        self.save()
    def tearDown(self):self.t.cleanup()
    def save(self):
        for file,obj in [('.https_probe_config.json',self.cfg),('.https_probe_status.json',self.state)]:
            p=self.base/file;p.write_text(json.dumps(obj));p.chmod(0o600)
    def test_valid_pairing(self):
        self.assertEqual(pair.verified_pairing(self.base)['uid'],self.cfg['uid'])
    def test_bad_device_or_multiple_rejected(self):
        for change in [{'connected_device_count':2},{'edge2_connected':False},
                       {'state':'callback_received_unverified_device'}]:
            d=self.state.copy();d.update(change);self.state=d;self.save()
            with self.assertRaises(pair.PairingError):pair.verified_pairing(self.base)
            self.state['state']='https_pairing_confirmed';self.state['edge2_connected']=True;self.state['connected_device_count']=1
    def test_old_callback_is_not_fake_heartbeat(self):
        self.state['updated_utc']=(datetime.now(timezone.utc)-timedelta(days=5)).isoformat();self.save()
        self.assertGreater(pair.verified_pairing(self.base)['age_seconds'],4*86400)
    def test_future_and_naive_date_blocked(self):
        for stamp in [(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'2026-10-17T12:00:00']:
            self.state['updated_utc']=stamp;self.save()
            with self.assertRaises(pair.PairingError):pair.verified_pairing(self.base)
    def test_symlink_and_open_permissions_blocked(self):
        p=self.base/'.https_probe_status.json';p.chmod(0o644)
        with self.assertRaises(pair.PairingError):pair.verified_pairing(self.base)
        p.unlink();p.symlink_to(self.base/'.https_probe_config.json')
        with self.assertRaises(pair.PairingError):pair.verified_pairing(self.base)

class OfflineCloudTests(unittest.TestCase):
    def setUp(self):
        self._temp_cloud_flag = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_cloud_flag.cleanup)
        self._cloud_flag_override = patch.object(dash, 'HTTPS_ENABLE_FLAG', pathlib.Path(self._temp_cloud_flag.name) / '.edge_https_cloud_enabled')
        self._cloud_flag_override.start()
        self.addCleanup(self._cloud_flag_override.stop)
        dash.HTTPS_ENABLE_FLAG.touch(mode=0o600)
        self.e=dash.HybridEngine('127.0.0.1',token='FAKE-token',uid='pi-owner',simulate=False)
        self.e._local_api=lambda x:(_ for _ in ()).throw(RuntimeError('mock phone not on LAN'))
        self.e._paired_status=lambda:{'uid':'pd-https-fresh','updated_utc':datetime.now(timezone.utc).isoformat(),'age_seconds':60}
        self.e._cloud_stop_preflight=lambda:{'code':200}
        self.e.https_cloud_enabled=True
    def tearDown(self):
        self.e._cloud_api=lambda x:{'code':200}
        self.e.shutdown()
    def test_correct_uid_pinned_after_preflight(self):
        route=self.e._choose_route()
        self.assertEqual(route,'cloud');self.assertEqual(self.e.cloud_session_uid,'pd-https-fresh')
        self.assertNotEqual(self.e.cloud_session_uid,self.e.uid)
    def test_cloud_disabled_blocks_before_preflight(self):
        self.e.https_cloud_enabled=False
        with self.assertRaisesRegex(RuntimeError,'disabled'):self.e._choose_route()
    def test_cloud_preflight_fail_closed(self):
        self.e._cloud_stop_preflight=lambda:(_ for _ in ()).throw(RuntimeError('mock 507'))
        with self.assertRaisesRegex(RuntimeError,'507'):self.e._choose_route()
        self.assertEqual(self.e.active_route,'unknown')
    def test_callback_is_unverified_not_online(self):
        s=self.e._keeper_snapshot()
        self.assertTrue(s['paired']);self.assertTrue(s['unverified'])
        self.assertIsNone(s['app_online']);self.assertIsNone(s['battery'])
        self.assertIn('connection unknown',s['message'])
    def test_missing_pairing_fails_closed(self):
        self.e._paired_status=lambda:(_ for _ in ()).throw(pair.PairingError('mock unavailable'))
        with self.assertRaises(RuntimeError):self.e._choose_route()
    def test_cloud_api_correct_uid_never_logs_secrets(self):
        self.e.cloud_session_uid='pd-https-fresh'
        def fake_run(cmd,**kwargs):
            body=json.loads(kwargs['input']);self.assertEqual(body['uid'],'pd-https-fresh')
            self.assertNotEqual(body['uid'],'pi-owner');self.assertEqual(body['token'],'FAKE-token')
            self.assertEqual(body['action'],'Stop');self.assertIn('--proto',cmd)
            return SimpleNamespace(returncode=0,stdout='{"code":200}\nHTTP_STATUS:200')
        with patch.object(dash.subprocess,'run',side_effect=fake_run):
            self.assertEqual(self.e._cloud_api({'command':'Function','action':'Stop','timeSec':0,'stopPrevious':1,'apiVer':1})['code'],200)
        self.assertTrue(self.e.status()['cloudCommandAccepted'])
    def test_507_sets_block_until_new_callback(self):
        self.e.cloud_session_uid='pd-https-fresh'
        older=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
        self.e._paired_status=lambda:{'uid':'pd-https-fresh','updated_utc':older,'age_seconds':60}
        with patch.object(dash.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{"code":507,"msg":"app offline"}\nHTTP_STATUS:200')):
            with self.assertRaisesRegex(RuntimeError,'507'):self.e._cloud_api({'command':'Function','action':'Stop'})
        snap=self.e._keeper_snapshot();self.assertTrue(self.e._cloud_507_blocked(snap))
        recent=datetime.now(timezone.utc)+timedelta(seconds=2)
        self.e._paired_status=lambda:{'uid':'pd-https-fresh','updated_utc':recent.isoformat(),'age_seconds':0}
        self.assertFalse(self.e._cloud_507_blocked(self.e._keeper_snapshot()))
    def test_malformed_cloud_response_fail_closed(self):
        self.e.cloud_session_uid='pd-https-fresh'
        with patch.object(dash.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='[]\nHTTP_STATUS:200')):
            with self.assertRaisesRegex(RuntimeError,'unexpected'):self.e._cloud_api({'command':'Function','action':'Stop'})
    def test_api_acceptance_never_physical_verification(self):
        self.e._choose_route()
        s=self.e.status()
        self.assertFalse(s['cloudPhysicalDeliveryVerified'])
        self.assertFalse(s['cloudConnected'])
        self.assertTrue(s['cloudPairingConfirmed'])
        self.assertTrue(s['cloudStatusUnverified'])

if __name__=='__main__':unittest.main()
