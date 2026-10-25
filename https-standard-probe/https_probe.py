#!/usr/bin/env python3
"""PulseDirector HTTPS-only STANDARD API pairing prototype.

No motor commands. Does not load, update, or restart the production services.
A dedicated callback with per-installation 'utoken' confirms HTTPS Standard API
pairing, independent of the Socket API integration.
"""
import argparse
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

BASE = Path(__file__).resolve().parent
CONFIG = BASE / '.https_probe_config.json'
STATUS = BASE / '.https_probe_status.json'
QR = BASE / 'https_probe_qr.jpg'
API = 'https://api.lovense-api.com/api/lan/getQrCode'
DEFAULT_TOKEN_FILE = BASE.parent / '.edge_cloud_token'  # Project-relative; no personal home path
API_TIMEOUT = 22


def utc():
    return datetime.now(timezone.utc).isoformat()


def _atomic(path, data):
    temp = path.with_name(path.name + '.tmp.' + secrets.token_hex(5))
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def init():
    if CONFIG.exists():
        raise RuntimeError('HTTPS prototype is already initialised. No settings changed.')
    data = {'uid': 'pd-https-' + secrets.token_hex(10),
            'utoken': secrets.token_urlsafe(40), 'created_utc': utc()}
    _atomic(CONFIG, json.dumps(data, indent=2).encode('utf-8'))
    _atomic(STATUS, json.dumps({'state': 'awaiting_callback', 'updated_utc': utc()}, indent=2).encode())
    print('Independent HTTPS pairing identity created. No credentials printed.')
    print('Config file:', CONFIG)
    print('Next: configure a *separate* public HTTPS callback to /lovense/callback on this probe.')


def config():
    if CONFIG.is_symlink() or not CONFIG.is_file():
        raise RuntimeError('Run init first. Missing/unsafe config file.')
    if CONFIG.stat().st_mode & 0o077:
        raise RuntimeError('Config permissions must be 0600. Run chmod 600 on it.')
    obj = json.loads(CONFIG.read_text(encoding='utf-8'))
    if not (isinstance(obj.get('uid'), str) and isinstance(obj.get('utoken'), str)):
        raise RuntimeError('Invalid prototype config')
    return obj


def _read_status():
    try:
        return json.loads(STATUS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _toy_summary(body):
    toys = body.get('toys')
    if isinstance(toys, str):
        try:
            toys = json.loads(toys)
        except ValueError:
            toys = None
    if not isinstance(toys, (dict, list)):
        return {'state': 'callback_received_no_toys', 'edge2_connected': False}
    rows = list(toys.values()) if isinstance(toys, dict) else toys
    rows = [item for item in rows if isinstance(item, dict)]
    # Strictly Edge 2 only; never use toy ID or device address in status output.
    def connected(t):
        return str(t.get('status', t.get('connected', '0'))).lower() in ('true', '1', 'connected')
    def model(t):
        return str(t.get('name', t.get('toyType', ''))).strip().lower()
    active = [item for item in rows if connected(item)]
    valid_edge2 = len(active) == 1 and model(active[0]) in ('edge 2', 'edge2', 'edge')
    return {'state': 'https_pairing_confirmed' if valid_edge2 else 'callback_received_unverified_device',
            'edge2_connected': valid_edge2,
            'connected_device_count': len(active)}


class CallbackHandler(BaseHTTPRequestHandler):
    server_version = 'PulseDirectorHttpsProbe/0.1'
    sys_version = ''

    def log_message(self, fmt, *args):
        # Deliberately avoid raw HTTP requests, IPs, QR, device IDs or secrets.
        pass

    def _reply(self, http, body):
        data = json.dumps(body).encode('utf-8')
        self.send_response(http)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._reply(404, {'error': 'Not found'})

    def do_POST(self):
        if urlsplit(self.path).path != '/lovense/callback' or self.path != '/lovense/callback':
            self._reply(404, {'error': 'Not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 32768:
                self._reply(413, {'error': 'Invalid payload size'})
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, TypeError, OverflowError, json.JSONDecodeError):
            self._reply(400, {'error': 'Invalid JSON'})
            return
        cfg = self.server.probe_config
        if not (hmac.compare_digest(str(payload.get('uid', '')), cfg['uid']) and
                hmac.compare_digest(str(payload.get('utoken', '')), cfg['utoken'])):
            self._reply(403, {'error': 'Not authorised'})
            return
        s = _toy_summary(payload)
        s['updated_utc'] = utc()
        with self.server.write_lock:
            _atomic(STATUS, json.dumps(s, indent=2).encode())
        self._reply(200, {'result': True, 'code': 200})
        print('Authenticated HTTPS callback received:', s['state'], '(no IDs recorded)', flush=True)


def serve(bind, port):
    if bind != '127.0.0.1':
        raise RuntimeError('Refusing to bind on a network interface. Use a controlled HTTPS tunnel to localhost.')
    server = ThreadingHTTPServer((bind, port), CallbackHandler)
    server.probe_config = config()
    server.write_lock = threading.Lock()
    print('Prototype callback listening on localhost:%d' % port, flush=True)
    print('This listener sends no motor commands. Leave it running during pairing.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _curl_json(url, body, token=False):
    proc = subprocess.run(['curl', '-q', '--silent', '--show-error', '--fail-with-body',
                           '--max-time', str(API_TIMEOUT), '--proto', '=https',
                           '-H', 'Content-Type: application/json',
                           '--data-binary', '@-', url],
                          input=json.dumps(body), text=True, capture_output=True,
                          timeout=API_TIMEOUT+5)
    if proc.returncode:
        raise RuntimeError('HTTPS request failed; curl exit %d. Check outbound connectivity.' % proc.returncode)
    try:
        result = json.loads(proc.stdout)
    except ValueError as e:
        raise RuntimeError('HTTPS QR API did not return JSON') from e
    if not isinstance(result, dict) or result.get('code') != 0:
        safe_code = result.get('code') if isinstance(result, dict) else 'unknown'
        raise RuntimeError('HTTPS QR API rejected request (code %s). No raw response printed.' % str(safe_code)[:25])
    return result


def qr(token_path, print_code=False):
    cfg = config()
    if token_path.is_symlink() or not token_path.is_file() or token_path.stat().st_mode & 0o077:
        raise RuntimeError('Token file must exist, not be a symlink, and have permissions 0600.')
    token = token_path.read_text(encoding='utf-8').strip()
    if not token:
        raise RuntimeError('Developer token is empty.')
    result = _curl_json(API, {'token': token, 'uid': cfg['uid'], 'utoken': cfg['utoken'], 'v': 2})
    data = result.get('data') or {}
    if not isinstance(data, dict):
        raise RuntimeError('Lovense QR response is invalid')
    pairing_code = data.get('code')
    if print_code and (not isinstance(pairing_code, str) or not re.fullmatch(r'[A-Za-z0-9]{4,32}', pairing_code)):
        # QR fallback remains available even if Lovense changes the code format.
        pairing_code = None
    qr_url = data.get('qr')
    if not isinstance(qr_url, str):
        raise RuntimeError('Lovense did not provide a QR image URL.')
    parsed = urlsplit(qr_url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not (host == 'lovense.com' or host.endswith('.lovense.com')):
        raise RuntimeError('QR URL did not pass HTTPS/Lovense host validation.')
    proc = subprocess.run(['curl', '-q', '--silent', '--show-error', '--fail', '--location',
                           '--max-time', '20', '--proto', '=https',
                           '--output', str(QR), qr_url], capture_output=True, timeout=25)
    if proc.returncode:
        QR.unlink(missing_ok=True)
        raise RuntimeError('QR download failed; curl exit %d' % proc.returncode)
    QR.chmod(0o600)
    if QR.stat().st_size > 3000000 or QR.stat().st_size < 200:
        QR.unlink(missing_ok=True)
        raise RuntimeError('Unexpected QR image size.')
    print('HTTPS-only QR saved privately to:', QR)
    # Only print to an explicitly requesting local subprocess, never by default.
    # The dashboard captures stdout and never writes the pairing code to logs.
    if print_code:
        print('PAIRING_CODE=' + (pairing_code or 'UNAVAILABLE'))
    print('Use a separate Lovense Standard API developer callback configured as /lovense/callback.')
    print('Do not post the QR online. No motor command has been sent.')


def status():
    d = _read_status()
    allowed = ('state', 'updated_utc', 'edge2_connected', 'connected_device_count')
    print(json.dumps({k:v for k,v in d.items() if k in allowed}, indent=2))


def main():
    ap=argparse.ArgumentParser(description='HTTPS-only Lovense Standard API pairing diagnostic, NO toy motor commands')
    sub=ap.add_subparsers(dest='action', required=True)
    sub.add_parser('init')
    sp=sub.add_parser('serve'); sp.add_argument('--bind',default='127.0.0.1'); sp.add_argument('--port', type=int,default=8787)
    p=sub.add_parser('qr'); p.add_argument('--token-file', type=Path,default=DEFAULT_TOKEN_FILE); p.add_argument('--print-code', action='store_true')
    sub.add_parser('status')
    args=ap.parse_args()
    if args.action=='init': init()
    elif args.action=='serve': serve(args.bind,args.port)
    elif args.action=='qr': qr(args.token_file, print_code=args.print_code)
    elif args.action=='status': status()

if __name__=='__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
        print('ERROR:', str(e), file=sys.stderr)
        sys.exit(1)
