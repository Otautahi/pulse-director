"""Read the independently authenticated Lovense HTTPS callback state.

The callback is event-based. It is NEVER a heartbeat/physical motor proof.
Only a stop-only HTTPS API preflight can establish current server acceptance.
"""
import json
import stat
from datetime import datetime, timezone
from pathlib import Path

PROBE = Path(__file__).resolve().parent / 'https-standard-probe'

class PairingError(RuntimeError):
    pass

def private_json(path):
    path = Path(path)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or (info.st_mode & 0o077) or info.st_size > 4096 or info.st_size < 5:
            raise PairingError('HTTPS pairing file missing, unsafe permissions, or invalid size: ' + path.name)
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError) as exc:
        raise PairingError('HTTPS pairing file unavailable or invalid: ' + path.name) from exc
    if not isinstance(data, dict):
        raise PairingError('HTTPS pairing file must be an object: ' + path.name)
    return data

def verified_pairing(probe_dir=PROBE, now=None):
    base = Path(probe_dir)
    cfg = private_json(base / '.https_probe_config.json')
    status = private_json(base / '.https_probe_status.json')
    uid,utoken = cfg.get('uid'), cfg.get('utoken')
    if (not isinstance(uid,str) or not uid.startswith('pd-https-') or
        len(uid)>120 or any(ch in uid for ch in ' ,\t\n\r') or
        not isinstance(utoken,str) or len(utoken)<32):
        raise PairingError('Invalid HTTPS pairing identity')
    if (status.get('state')!='https_pairing_confirmed' or
        status.get('edge2_connected') is not True or
        type(status.get('connected_device_count')) is not int or
        status.get('connected_device_count')!=1):
        raise PairingError('No authenticated single-Edge-2 HTTPS callback recorded')
    try:
        stamp=datetime.fromisoformat(status['updated_utc'].replace('Z','+00:00'))
        if stamp.tzinfo is None: raise ValueError('missing timezone')
        now=now or datetime.now(timezone.utc)
        age=(now-stamp).total_seconds()
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as exc:
        raise PairingError('HTTPS callback timestamp invalid') from exc
    if age < -120:
        raise PairingError('HTTPS callback timestamp is in the future')
    return {'uid':uid,'updated_utc':stamp.isoformat(), 'age_seconds':round(max(age,0)),
            'message':'HTTPS callback was authenticated; NOT a live device heartbeat'}
