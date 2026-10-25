"""No device/network I/O: v4.6 shared-cloud portability + safety regressions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import edge_dashboard as pd
import edge2_pairing_ui
from edge2_https_pairing import verified_pairing


class SharedCloudDev3Tests(unittest.TestCase):
    def test_cloud_disabled_in_staged_release(self):
        self.assertFalse(pd.HTTPS_ENABLE_FLAG.exists(),
                         'Development cloud-enable flag must not be copied into new release')

    def test_token_requires_regular_owner_only_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / 'cloud.token'
            good.write_text('fake-token-used-for-offline-test', encoding='utf-8')
            good.chmod(0o600)
            self.assertEqual(pd.read_cloud_token(good), 'fake-token-used-for-offline-test')
            good.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, 'owner-only'):
                pd.read_cloud_token(good)
            good.chmod(0o600)
            link = Path(tmp) / 'link'
            link.symlink_to(good)
            with self.assertRaises(RuntimeError):
                pd.read_cloud_token(link)

    def test_shared_environment_override_is_project_external_and_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp)
            env = os.environ.copy()
            env.update(PULSEDIRECTOR_CLOUD_TOKEN_FILE=str(fake / 'token'),
                       PULSEDIRECTOR_HTTPS_PROBE_DIR=str(fake / 'probe'))
            code = ('import edge_dashboard as d; import edge2_https_pairing as h; '
                    'print(d.CLOUD_TOKEN_FILE); print(h.PROBE)')
            result = subprocess.run([sys.executable, '-c', code], env=env, cwd=ROOT,
                                    capture_output=True, text=True, timeout=15, check=True)
            self.assertEqual(result.stdout.splitlines(), [str(fake / 'token'), str(fake / 'probe')])

    def test_pairing_reuses_shared_files_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = base / '.https_probe_config.json'
            stat = base / '.https_probe_status.json'
            cfg.write_text(json.dumps({'uid': 'pd-https-' + '1'*20, 'utoken': '2'*40}))
            stat.write_text(json.dumps({'state': 'https_pairing_confirmed',
                                        'edge2_connected': True, 'connected_device_count': 1,
                                        'updated_utc': datetime.now(timezone.utc).isoformat()}))
            cfg.chmod(0o600)
            stat.chmod(0o600)
            before = (cfg.read_bytes(), stat.read_bytes())
            info = verified_pairing(probe_dir=base)
            self.assertGreaterEqual(info['age_seconds'], 0)
            self.assertEqual((cfg.read_bytes(), stat.read_bytes()), before)

    def test_shared_qr_generation_is_refused_before_subprocess(self):
        with patch.dict(os.environ, {'PULSEDIRECTOR_HTTPS_PROBE_DIR': '/nonexistent/shared'}):
            class CannotRun:
                def __call__(self, *args, **kwargs):
                    raise AssertionError('QR generator must not be called')
            manager = edge2_pairing_ui.PairingQRManager(run=CannotRun())
            with self.assertRaisesRegex(RuntimeError, 'read-only'):
                manager.generate(SimpleNamespace(simulate=False, token='fake-token', status=lambda: {'running': False}))

    def test_connection_labels_do_not_claim_game_mode_enabled(self):
        self.assertIn('Local API reachable', pd.HTML)
        self.assertIn('Game Mode setting unverified', pd.HTML)
        self.assertNotIn("'Connected (LAN)'", pd.HTML)

    def test_shared_env_does_not_grant_cloud_control(self):
        with patch.dict(os.environ, {'PULSEDIRECTOR_HTTPS_PROBE_DIR': '/nonexistent/shared'}):
            e = pd.HybridEngine('127.0.0.1', token='fake-token', uid='offline', simulate=True)
            try:
                self.assertFalse(e.https_cloud_enabled)
                self.assertEqual(e.status()['cloudPairingSource'], 'shared-read-only')
            finally:
                e.shutdown()

if __name__ == '__main__':
    unittest.main()
