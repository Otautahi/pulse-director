"""Offline tests for the Standard API code and QR belonging to one response."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

SRC=Path(__file__).resolve().parents[1]/'https-standard-probe'/'https_probe.py'
spec=importlib.util.spec_from_file_location('probe_under_test',SRC)
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
class PairingCodeTests(TestCase):
    def test_single_response_returns_qr_and_its_code(self):
        with tempfile.TemporaryDirectory() as td:
            qr=Path(td)/'https_probe_qr.jpg';token=Path(td)/'token'
            token.write_text('NOT-REAL-TOKEN');token.chmod(0o600)
            def fake_subprocess(args,**kw):
                self.assertEqual(args[-2],str(qr))
                qr.write_bytes(b'\xff\xd8\xff'+b'x'*512);qr.chmod(0o600)
                return SimpleNamespace(returncode=0)
            buf=io.StringIO()
            with patch.object(probe,'QR',qr),patch.object(probe,'config',return_value={'uid':'mockuid','utoken':'mockutoken'}), \
                 patch.object(probe,'_curl_json',return_value={'data':{'qr':'https://example.lovense.com/a.jpg','code':'012345'}}) as fetch, \
                 patch.object(probe.subprocess,'run',side_effect=fake_subprocess),contextlib.redirect_stdout(buf):
                probe.qr(token,print_code=True)
            self.assertIn('PAIRING_CODE=012345',buf.getvalue())
            self.assertEqual(fetch.call_count,1)
            self.assertNotIn('NOT-REAL-TOKEN',buf.getvalue())
    def test_no_code_on_old_terminal_command(self):
        with tempfile.TemporaryDirectory() as td:
            qr=Path(td)/'https_probe_qr.jpg';token=Path(td)/'token'
            token.write_text('NOT-REAL-TOKEN');token.chmod(0o600)
            def fake_subprocess(args,**kw):
                qr.write_bytes(b'\xff\xd8\xff'+b'x'*512);qr.chmod(0o600)
                return SimpleNamespace(returncode=0)
            buf=io.StringIO()
            with patch.object(probe,'QR',qr),patch.object(probe,'config',return_value={'uid':'mockuid','utoken':'mockutoken'}), \
                 patch.object(probe,'_curl_json',return_value={'data':{'qr':'https://example.lovense.com/a.jpg','code':'012345'}}), \
                 patch.object(probe.subprocess,'run',side_effect=fake_subprocess),contextlib.redirect_stdout(buf):
                probe.qr(token)
            self.assertNotIn('PAIRING_CODE',buf.getvalue())
