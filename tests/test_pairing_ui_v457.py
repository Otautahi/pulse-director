"""No-hardware, no-network tests for the explicit authenticated pairing UI."""
import base64
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from edge2_pairing_ui import PairingQRManager
import edge_dashboard as dashboard

JPEG=b'\xff\xd8\xff'+b'1234567890'*40+b'\xff\xd9'

class Engine:
    def __init__(self,run=False,token='configured',simulate=False):
        self.run=run; self.token=token; self.simulate=simulate
    def status(self):return {'running':self.run}

class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.probe=Path(self.tmp.name)/'https_probe.py'
        self.probe.write_text('# script controlled by offline test\n')
        self.calls=[];self.clock=[1000]
    def mockrun(self,argv,**kw):
        self.calls.append(argv)
        qr=self.probe.parent/'https_probe_qr.jpg';qr.write_bytes(JPEG);qr.chmod(0o600)
        return SimpleNamespace(returncode=0,stdout='HTTPS-only QR saved privately to: hidden\nPAIRING_CODE=483920',stderr='token EXPOSED IN STDERR')
    def manager(self):
        return PairingQRManager(probe=self.probe,now=lambda:self.clock[0],run=self.mockrun)
    def test_pairing_reuses_fixed_probe_and_returns_image_without_secrets(self):
        q=self.manager().generate(Engine())
        self.assertEqual(base64.b64decode(q['image'].split(',',1)[1]),JPEG)
        self.assertNotIn('token EXPOSED',str(q)); self.assertNotIn('SECRET',str(q))
        self.assertEqual(self.calls[0][-3:], [str(self.probe),'qr','--print-code'])
        self.assertEqual(q['code'],'483920')
        self.assertIn('expiresUtc',q)
        self.assertNotIn('token EXPOSED',str(q))
    def test_missing_or_invalid_pair_code_cannot_leak(self):
        def mockrun(argv, **kw):
            qr=self.probe.parent/'https_probe_qr.jpg';qr.write_bytes(JPEG);qr.chmod(0o600)
            return SimpleNamespace(returncode=0,stdout='PAIRING_CODE=UNAVAILABLE')
        q=PairingQRManager(self.probe,now=lambda:1000,run=mockrun).generate(Engine())
        self.assertIsNone(q['code'])
        def badrun(argv, **kw):
            qr=self.probe.parent/'https_probe_qr.jpg';qr.write_bytes(JPEG);qr.chmod(0o600)
            return SimpleNamespace(returncode=0,stdout='PAIRING_CODE=<script>alert(1)</script>')
        with self.assertRaisesRegex(RuntimeError,'Invalid code'):
            PairingQRManager(self.probe,now=lambda:1000,run=badrun).generate(Engine())
    def test_code_is_only_returned_after_authenticated_request(self):
        replies=[]
        dummy=dashboard.Handler.__new__(dashboard.Handler)
        dummy.headers={'X-Edge-Key':'wrong','Content-Length':'2'}
        dummy.server=SimpleNamespace(key='secret',engine=Engine(),pair_qr=SimpleNamespace(generate=lambda e:(_ for _ in ()).throw(AssertionError('should not call'))))
        dummy.path='/api/cloud/pair-qr';dummy.rfile=io.BytesIO(b'{}')
        dummy._json=lambda code,data:replies.append((code,data))
        dummy.do_POST();self.assertEqual(replies[0][0],401)
    def test_no_automatic_call_and_rate_limit(self):
        m=self.manager();self.assertFalse(self.calls)
        m.generate(Engine())
        with self.assertRaisesRegex(RuntimeError,'wait 20 seconds'):m.generate(Engine())
        self.clock[0]+=21;m.generate(Engine());self.assertEqual(len(self.calls),2)
    def test_active_motor_session_refused(self):
        with self.assertRaisesRegex(RuntimeError,'Stop the current session'):
            self.manager().generate(Engine(run=True))
        self.assertFalse(self.calls)
    def test_simulator_or_missing_token_refused(self):
        for e in [Engine(simulate=True),Engine(token='')]:
            with self.assertRaisesRegex(RuntimeError,'credentials'):self.manager().generate(e)
        self.assertFalse(self.calls)
    def test_failure_does_not_disclose_subprocess_output(self):
        m=PairingQRManager(probe=self.probe,run=lambda *a,**kw:SimpleNamespace(returncode=1,stdout='SECRET',stderr='SECRET'),now=lambda:1000)
        with self.assertRaisesRegex(RuntimeError,'generation failed') as ctx:m.generate(Engine())
        self.assertNotIn('SECRET',str(ctx.exception))
    def test_untrusted_probe_symlink_refused(self):
        self.probe.unlink();self.probe.symlink_to(Path(self.tmp.name)/'missing')
        with self.assertRaisesRegex(RuntimeError,'unavailable'):self.manager().generate(Engine())
    def test_bad_qr_permissions_refused(self):
        def bad(*args,**kw):
            qr=self.probe.parent/'https_probe_qr.jpg';qr.write_bytes(JPEG);qr.chmod(0o644)
            return SimpleNamespace(returncode=0)
        with self.assertRaisesRegex(RuntimeError,'permissions'):
            PairingQRManager(self.probe,now=lambda:1000,run=bad).generate(Engine())
    def test_unexpected_qr_bytes_refused(self):
        def bad(*args,**kw):
            qr=self.probe.parent/'https_probe_qr.jpg';qr.write_bytes(b'X'*300);qr.chmod(0o600)
            return SimpleNamespace(returncode=0)
        with self.assertRaisesRegex(RuntimeError,'unsupported QR'):
            PairingQRManager(self.probe,now=lambda:1000,run=bad).generate(Engine())

class DashboardTests(unittest.TestCase):
    def test_motor_logic_unmodified(self):
        import hashlib
        s=Path(dashboard.__file__).read_text()
        # The Stop UX change necessarily updates Engine safety state. Lock the
        # actual motor-output, pattern and motor-worker implementations instead.
        parts=[]
        for heading in ('    def _send_levels(', '    def _pattern(', '    def _loop('):
            begin=s.index(heading)
            end=s.find('\n    def ',begin+len(heading))
            if end<0:end=s.find('\n    @staticmethod',begin+len(heading))
            parts.append(s[begin:end].strip())
        self.assertEqual(hashlib.sha256(('\n\n'.join(parts)).encode()).hexdigest(),
                         'ea7600d53b6be000a4ddb9eab0acc6f1f75881db72fb3bf260e00029097d03bc')
    def test_dashboard_auth_and_qr_handler(self):
        calls=[]
        dummy=dashboard.Handler.__new__(dashboard.Handler)
        dummy.headers={'X-Edge-Key':'key', 'Content-Length':'2'}
        dummy.server=SimpleNamespace(key='key',engine=object.__new__(dashboard.HybridEngine),pair_qr=SimpleNamespace(generate=lambda e:calls.append(True) or {'image':'data:image/jpeg;base64,AA=='}))
        dummy.path='/api/cloud/pair-qr';dummy.rfile=io.BytesIO(b'{}')
        replies=[];dummy._json=lambda code,data:replies.append((code,data))
        dummy.do_POST();self.assertEqual(replies[0][0],200);self.assertEqual(calls,[True])
        dummy.headers['X-Edge-Key']='wrong';dummy.rfile=io.BytesIO(b'{}');dummy.do_POST()
        self.assertEqual(replies[-1][0],401);self.assertEqual(calls,[True])
    def test_unauthorized_pairing_never_exposes_image(self):
        src=Path(dashboard.__file__).read_text()
        self.assertIn('if self._needs_auth(): return',src[src.index('    def do_POST'):])
        self.assertIn('self.server.pair_qr.generate(self.server.engine)',src)
        self.assertIn('No new pairing requested',dashboard.HTML)
        self.assertIn('Show pairing QR or code',dashboard.HTML)
        self.assertIn('Input QR Code Number',dashboard.HTML)
        self.assertIn('hidePairingSecrets()',dashboard.HTML)
        self.assertIn("img-src 'self' data:",src)
        self.assertIn("pairingWaiting",dashboard.HTML)

if __name__=='__main__':unittest.main()
