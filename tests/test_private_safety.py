"""Offline-only regression tests for hybrid safety backport.
Never contacts a real toy, network endpoint, cloud service or local Cloud Keeper.
"""
import io
import json
import pathlib
import sys
import threading
import tempfile
import time
from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import edge_dashboard as m


def toy_data(connected=True, name='edge'):
    return {'code': 200, 'data': {'toys': json.dumps({'a': {'name':name, 'battery': 66,
                                            'status': '1' if connected else '0'}})}}


class FakeIO:
    def __init__(self):
        self.guard = threading.Lock()
        self.lan_connected = True
        self.lan_online = True
        self.cloud_online = True
        self.cloud_connected = True
        self.cloud_app_online = True
        self.cloud_reject_stop = False
        self.lan_reject_stop = False
        self.calls = []
    def lan(self, data):
        with self.guard:
            self.calls.append(('lan', data.copy()))
            if not self.lan_online:
                raise RuntimeError('mock LAN unreachable')
            if data['command']=='GetToys':
                return toy_data(self.lan_connected)
            if not self.lan_connected or (data.get('action')=='Stop' and self.lan_reject_stop):
                raise RuntimeError('mock Lovense code 402')
            return {'code':200}
    def cloud(self, data):
        with self.guard:
            self.calls.append(('cloud',data.copy()))
            if not self.cloud_online or (data.get('action')=='Stop' and self.cloud_reject_stop):
                raise RuntimeError('mock Lovense cloud code 507')
            return {'code':200}
    def keeper(self):
        connected=self.cloud_connected
        return {'fresh':True,'paired':connected,'connected':connected,'battery':66,'state':'device_connected' if connected else 'disconnected',
                'age':0,'last_event_utc':'2026-10-17T00:00:00+00:00','last_event_age':30,
                'unverified':False,'zero_unverified':False,'app_online':self.cloud_app_online,
                'message':'mock keeper'}
    def snapshot(self):
        with self.guard: return list(self.calls)

class HybridBackportTests(unittest.TestCase):
    @staticmethod
    def until(fn, timeout=6):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if fn():return True
            time.sleep(.025)
        return bool(fn())
    def setUp(self):
        self._temp_cloud_flag = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_cloud_flag.cleanup)
        self._cloud_flag_override = patch.object(m, 'HTTPS_ENABLE_FLAG', pathlib.Path(self._temp_cloud_flag.name) / '.edge_https_cloud_enabled')
        self._cloud_flag_override.start()
        self.addCleanup(self._cloud_flag_override.stop)
        m.HTTPS_ENABLE_FLAG.touch(mode=0o600)
        self.fake=FakeIO()
        self.engine=m.HybridEngine('127.0.0.1',token='fake-offline-test-only',uid='test',simulate=False)
        self.engine._local_api=self.fake.lan
        self.engine._cloud_api=self.fake.cloud
        self.engine._keeper_snapshot=self.fake.keeper
        self.engine.https_cloud_enabled=True
        self.engine._paired_status=lambda:{'uid':'pd-https-offline-test', 'updated_utc':'2026-10-17T08:15:58+00:00', 'age_seconds':0}
    def tearDown(self):
        self.engine.shutdown()

    def test_lan_loss_fault_latch_and_recovery_stops_on_lan_only(self):
        self.engine.start({'mode':'manual','max':5,'motor1':4,'motor2':2})
        self.assertEqual(self.engine.status()['connectionMode'],'lan')
        self.assertTrue(self.until(lambda:self.engine.status()['sessionCommands']>0))
        self.fake.lan_connected=False
        self.assertTrue(self.until(lambda:self.engine.status()['faultLatched']))
        s=self.engine.status()
        self.assertEqual(s['faultRoute'],'lan')
        self.assertFalse(s['running']);self.assertTrue(s['stopPending'])
        with self.assertRaises(RuntimeError):self.engine.start({'mode':'wave'})
        with self.assertRaises(RuntimeError):self.engine.test()
        with self.assertRaises(RuntimeError):self.engine.acknowledge_fault()
        ix=len(self.fake.snapshot())
        self.fake.lan_connected=True
        self.engine.recovery_wake.set()
        self.assertTrue(self.until(lambda:not self.engine.status()['stopPending']))
        recovered=self.fake.snapshot()[ix:]
        self.assertGreaterEqual(len([z for z in recovered if z[0]=='lan' and z[1].get('action')=='Stop']),3)
        self.assertFalse([z for z in recovered if z[0]=='cloud' and z[1].get('action')=='Stop'])
        self.assertFalse([z for z in recovered if z[1].get('action','').startswith('Vibrate')])
        self.engine.acknowledge_fault()
        self.assertFalse(self.engine.status()['faultLatched'])

    def test_wifi_loss_does_not_route_a_failed_lan_stop_to_cloud(self):
        self.engine.start({'mode':'wave','max':5,'minutes':1})
        self.assertTrue(self.until(lambda:self.engine.status()['sessionCommands']>0))
        self.fake.lan_online=False
        self.assertTrue(self.until(lambda:self.engine.status()['faultLatched']))
        self.assertEqual(self.engine.status()['faultRoute'],'lan')
        self.assertTrue(self.engine.status()['stopPending'])
        ix=len(self.fake.snapshot())
        self.fake.lan_online=True
        self.engine.recovery_wake.set()
        self.assertTrue(self.until(lambda:not self.engine.status()['stopPending']))
        self.assertFalse([z for z in self.fake.snapshot()[ix:] if z[0]=='cloud' and z[1].get('action')=='Stop'])

    def test_cloud_keeper_loss_pins_stop_and_recovery_to_cloud(self):
        self.fake.lan_online=False
        self.engine.start({'mode':'manual','max':5,'motor1':3,'motor2':2,'minutes':1})
        self.assertEqual(self.engine.status()['connectionMode'],'cloud')
        self.assertTrue(self.until(lambda:self.engine.status()['sessionCommands']>0))
        self.fake.cloud_online=False
        self.fake.cloud_connected=False
        self.assertTrue(self.until(lambda:self.engine.status()['faultLatched']))
        self.assertEqual(self.engine.status()['faultRoute'],'cloud')
        ix=len(self.fake.snapshot())
        self.fake.lan_online=True  # recovering LAN MUST NOT steal cloud STOP
        self.fake.cloud_connected=True
        self.fake.cloud_online=True
        self.engine._paired_status=lambda:{'uid':'pd-https-offline-test',
              'updated_utc':(datetime.now(timezone.utc)+timedelta(seconds=2)).isoformat(),'age_seconds':0}
        self.engine.recovery_wake.set()
        self.assertTrue(self.until(lambda:self.engine.status()['stopAcks']>=3))
        self.assertTrue(self.engine.status()['stopPending'])  # HTTP 200 CANNOT UNLOCK cloud
        rec=self.fake.snapshot()[ix:]
        self.assertGreaterEqual(len([z for z in rec if z[0]=='cloud' and z[1].get('action')=='Stop']),3)
        self.assertFalse([z for z in rec if z[0]=='lan' and z[1].get('action')=='Stop'])
        with self.assertRaisesRegex(RuntimeError,'POWER OFF'):
            self.engine.acknowledge_fault()
        self.engine.acknowledge_fault(physical_off=True)
        self.assertFalse(self.engine.status()['faultLatched'])

    def test_cloud_stop_rejected_never_unlocks(self):
        self.fake.lan_online=False
        self.engine.start({'mode':'wave','max':5,'minutes':1})
        self.fake.cloud_reject_stop=True
        with self.assertRaises(RuntimeError):self.engine.stop('Stop failed')
        self.assertTrue(self.engine.status()['faultLatched'])
        self.assertTrue(self.engine.status()['stopPending'])
        with self.assertRaises(RuntimeError):self.engine.acknowledge_fault()
        self.fake.cloud_reject_stop=False
        self.engine._paired_status=lambda:{'uid':'pd-https-offline-test',
            'updated_utc':(datetime.now(timezone.utc)+timedelta(seconds=2)).isoformat(),'age_seconds':0}
        self.engine.recovery_wake.set()
        self.assertTrue(self.until(lambda:self.engine.status()['stopAcks']>=3))
        self.assertTrue(self.engine.status()['stopPending'])
        self.engine.acknowledge_fault(physical_off=True)
        self.assertFalse(self.engine.status()['faultLatched'])

    def test_active_lan_disconnection_does_not_show_keeper_as_connected(self):
        self.engine.start({'mode':'wave','max':5,'minutes':1})
        self.fake.lan_connected=False
        s=self.engine.refresh_toys()
        self.assertFalse(s['toyConnected'])
        self.assertEqual(s['connectionMode'],'lan')

    def test_hybrid_stop_during_delayed_start_prevents_restart(self):
        entered,release=threading.Event(),threading.Event()
        normal=self.engine._choose_route
        out={}
        def stalled():
            entered.set();release.wait(3)
            return normal()
        def start():
            try:self.engine.start({'mode':'wave','max':5,'minutes':1})
            except RuntimeError as e:out['error']=str(e)
        with patch.object(self.engine,'_choose_route',side_effect=stalled):
            t=threading.Thread(target=start);t.start()
            try:
                self.assertTrue(entered.wait(2))
                self.engine.stop('Explicit STOP')
            finally:
                release.set();t.join(3)
        self.assertFalse(t.is_alive())
        self.assertFalse(self.engine.status()['running'])
        self.assertIn('cancel',out.get('error','').lower())

    def test_hybrid_stop_during_delayed_motor_test_prevents_restart(self):
        entered,release=threading.Event(),threading.Event()
        normal=self.engine._choose_route
        out={}
        def stalled():
            entered.set();release.wait(3)
            return normal()
        def test_motor():
            try:self.engine.test()
            except RuntimeError as e:out['error']=str(e)
        with patch.object(self.engine,'_choose_route',side_effect=stalled):
            t=threading.Thread(target=test_motor);t.start()
            try:
                self.assertTrue(entered.wait(2))
                self.engine.stop('Explicit STOP')
            finally:
                release.set();t.join(3)
        self.assertFalse(self.engine.status()['running'])
        self.assertIn('cancel',out.get('error','').lower())

    def test_switching_patterns_remains_possible_after_internal_stop(self):
        self.engine.start({'mode':'manual','max':5,'motor1':4,'motor2':3})
        s=self.engine.start({'mode':'wave','max':5,'minutes':1})
        self.assertTrue(s['running']);self.assertEqual(s['mode'],'wave')

    def test_stale_lan_route_during_idle_can_switch_to_cloud(self):
        self.fake.lan_online=False
        self.assertEqual(self.engine.refresh_toys()['connectionMode'],'cloud')
        self.assertTrue(self.engine.start({'mode':'wave','max':5,'minutes':1})['running'])
        self.assertEqual(self.engine.status()['connectionMode'],'cloud')

    def test_device_validation_rejects_multiple_and_max2(self):
        for payload in (
            {'code':200,'data':{'toys':json.dumps({'a':{'name':'edge','status':'1'},'b':{'name':'edge','status':'1'}})}},
            toy_data(name='max2')):
            self.assertIsNone(m.Engine._extract_toy(payload))

    def test_normal_stop_success_no_fault(self):
        self.engine.start({'mode':'wave','max':5,'minutes':1})
        self.engine.stop('Manual')
        self.assertFalse(self.engine.status()['faultLatched'])

    def test_stop_route_remains_pinned_while_stop_request_is_delayed(self):
        self.engine.start({'mode':'wave','max':5,'minutes':1})
        entered, go = threading.Event(),threading.Event()
        original=self.engine._send_stop
        errors=[]
        def delayed_stop():
            entered.set()
            if not go.wait(3):
                raise RuntimeError('test timeout')
            return original()
        def press_stop():
            try:self.engine.stop('User Stop')
            except RuntimeError as e:errors.append(str(e))
        with patch.object(self.engine,'_send_stop',side_effect=delayed_stop):
            t=threading.Thread(target=press_stop);t.start()
            try:
                self.assertTrue(entered.wait(2))
                self.fake.lan_online=False
                state=self.engine.refresh_toys()
                self.assertEqual(state['connectionMode'],'lan')
                self.assertFalse(state['toyConnected'])
                self.assertEqual(self.engine.active_route,'lan')
                self.fake.lan_online=True
            finally:
                go.set();t.join(4)
        self.assertFalse(t.is_alive());self.assertFalse(errors)
        self.assertFalse(self.engine.status()['running'])

    def test_lan_and_cloud_stop_payloads_remain_compatible(self):
        self.engine.start({'mode':'wave','max':5,'minutes':1})
        self.engine.stop()
        stops=[item for route,item in self.fake.snapshot() if route=='lan' and item.get('action')=='Stop']
        self.assertTrue(stops)
        self.assertEqual(stops[-1].get('stopPrevious'),1)
        self.fake.lan_online=False
        self.engine.start({'mode':'wave','max':5,'minutes':1})
        self.engine.stop()
        stops=[item for route,item in self.fake.snapshot() if route=='cloud' and item.get('action')=='Stop']
        self.assertTrue(stops)
        self.assertEqual(stops[-1]['stopPrevious'],1)  # Confirmed accepted in standalone HTTPS pilot

    def test_connection_warning_clears_after_acknowledged_cloud_fault(self):
        self.fake.lan_online=False
        self.engine.start({'mode':'wave','max':5,'minutes':1})
        self.fake.cloud_connected=False
        self.engine._abort_cloud_session('connection lost')
        self.assertTrue(self.engine.status()['connectionWarning'])
        self.assertTrue(self.engine.status()['stopPending'])
        with self.assertRaises(RuntimeError):self.engine.acknowledge_fault()
        self.engine.acknowledge_fault(physical_off=True)
        self.assertFalse(self.engine.status()['connectionWarning'])

    def test_fault_status_reached_by_api_and_ui_controls_present(self):
        self.assertIn('/api/ack-fault',m.HTML)
        self.assertIn('id="safetyFault"',m.HTML)
        self.assertIn('id="ackFault"',m.HTML)
        self.assertIn('s.faultLatched',m.HTML)

    def test_new_start_blocked_while_stop_is_awaiting_remote_ack(self):
        self.engine.start({'mode':'wave','max':5,'minutes':1})
        entered, go = threading.Event(),threading.Event()
        send=self.engine._send_stop
        def delayed():
            entered.set();go.wait(3)
            return send()
        with patch.object(self.engine,'_send_stop',side_effect=delayed):
            t=threading.Thread(target=lambda:self.engine.stop('Stopping'))
            t.start()
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaisesRegex(RuntimeError,'Stop pending'):
                    self.engine.start({'mode':'wave','max':5,'minutes':1})
                with self.assertRaisesRegex(RuntimeError,'Stop pending'):
                    self.engine.test()
            finally:
                go.set();t.join(3)
        self.assertFalse(self.engine.status()['running'])

    def test_non_object_json_raises_runtime_error_not_attribute_error(self):
        engine=object.__new__(m.Engine)
        engine.simulate=False
        engine.url='http://127.0.0.1:20010/command'
        for payload in (b'null',b'[]',b'"bad"'):
            with patch.object(m,'urlopen',return_value=io.BytesIO(payload)):
                with self.assertRaisesRegex(RuntimeError,'unexpected response'):
                    engine._api({'command':'GetToys'})

if __name__=='__main__':unittest.main()
