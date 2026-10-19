"""Access-key protected, explicit HTTPS pairing QR generation for the private dashboard.

This module does NOT change device control or callback handling. The external
https_probe.py remains the single owner of pairing identity and QR downloads.
"""
import base64
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import threading
import time

PROBE = Path.home() / 'edge-ai' / 'https-standard-probe' / 'https_probe.py'


class PairingQRManager:
    def __init__(self, probe=PROBE, now=time.monotonic, run=subprocess.run):
        self.probe = Path(probe)
        self.now = now
        self.run = run
        self.lock = threading.Lock()
        self.last_started = float('-inf')

    def generate(self, engine):
        # Require an authenticated request at the HTTP handler level as well.
        if getattr(engine, 'simulate', False) or not getattr(engine, 'token', None):
            raise RuntimeError('HTTPS Cloud credentials are not configured')
        if engine.status().get('running'):
            raise RuntimeError('Stop the current session before requesting a pairing QR')
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('A pairing request is already running')
        try:
            if self.now() - self.last_started < 20:
                raise RuntimeError('Please wait 20 seconds before generating another QR')
            self.last_started = self.now()
            if self.probe.is_symlink() or not self.probe.is_file():
                raise RuntimeError('HTTPS pairing script unavailable; use the existing terminal QR command')
            # Only call our installed local script, never a user-supplied URL or shell.
            try:
                result = self.run([sys.executable, str(self.probe), 'qr', '--print-code'],
                                  capture_output=True, text=True, timeout=55, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError('Lovense QR request timed out or could not start') from exc
            if result.returncode != 0:
                raise RuntimeError('Lovense QR generation failed. Check the HTTPS pairing script and its token configuration on the Pi.')
            # Parse one purpose-specific line from captured stdout. Never log stdout.
            # The API's data.code belongs to the same getQrCode response as the image.
            matches = [line.partition('PAIRING_CODE=')[2] for line in (getattr(result, 'stdout', '') or '').splitlines()
                       if line.startswith('PAIRING_CODE=')]
            if len(matches) > 1:
                raise RuntimeError('Unexpected multiple pairing codes from local script')
            code = matches[0] if matches else None
            if code == 'UNAVAILABLE':
                code = None
            if code is not None and not re.fullmatch(r'[A-Za-z0-9]{4,32}', code):
                raise RuntimeError('Invalid code format from local QR script')
            qrfile = self.probe.parent / 'https_probe_qr.jpg'
            if qrfile.is_symlink() or not qrfile.is_file():
                raise RuntimeError('QR image unavailable or unsafe')
            stat = qrfile.stat()
            if stat.st_mode & 0o077 or not 200 <= stat.st_size <= 3_000_000:
                raise RuntimeError('QR image permissions or size invalid')
            raw = qrfile.read_bytes()
            if raw.startswith(b'\xff\xd8\xff'):
                kind = 'image/jpeg'
            elif raw.startswith(b'\x89PNG\r\n\x1a\n'):
                kind = 'image/png'
            else:
                raise RuntimeError('Lovense returned an unsupported QR image')
            issued = datetime.now(timezone.utc)
            return {'image': 'data:' + kind + ';base64,' + base64.b64encode(raw).decode('ascii'),
                    'code': code,
                    'issuedUtc': issued.isoformat(),
                    'expiresUtc': (issued + timedelta(hours=4)).isoformat()}
        finally:
            self.lock.release()
