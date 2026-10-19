# PulseDirector v4.6 — Unified Hybrid Edition (development candidate)

**Unreleased / experimental. Not the stable build. Not approved for automatic deployment to a live device.**

The v4.6 development tree unifies the v4.5 public LAN controller with the extended private v4.5.7 hybrid controller. The private application is the functionality superset and the shared `edge2_director.py` is identical to the public version. This candidate incorporates the v4.6 Quiet Stop behaviour and two explicit runtime profiles.

## Profiles

- **LAN-only** (`--profile lan`) runs the base Edge 2 Game Mode controller. No cloud token is read and the cloud pairing API returns 404. The pairing panel is hidden. This is the closest compatibility option for the earlier public release.
- **Hybrid** (`--profile hybrid`) runs the private LAN/HTTPS Cloud engine with optional HTTPS pairing, route-pinned commands, and cloud diagnostics. Cloud is **not automatically enabled** by this flag. A properly configured token, a separately authenticated callback, a recent pairing event and the intentionally created `.edge_https_cloud_enabled` flag are necessary before any cloud commands can be attempted. Prior callback status is not a live heartbeat or proof that the device responded.

Both profiles use the shared Autonomous Director and motor-pattern engine; only one Edge 2 is supported. The Max 2 and multi-device control are **not implemented**.

## Offline first

From an isolated checkout (not the live deployment):

```bash
python3 -m unittest discover -s tests -q
python3 -m py_compile edge_dashboard.py edge2_director.py edge2_https_pairing.py edge2_pairing_ui.py https-standard-probe/https_probe.py
python3 edge_dashboard.py --profile lan --simulate --port 8876
```

This simulation listens on `127.0.0.1:8876`. If using a headless Pi, an SSH tunnel can access it without exposing the service. The simulator does **not** control a real device.

To test the hybrid UI without any credentials or device I/O:

```bash
python3 edge_dashboard.py --profile hybrid --simulate --port 8876
```

Before any live LAN test, explicitly provide **your own** phone address and a trusted local bind address, for example:

```bash
python3 edge_dashboard.py --profile lan --phone YOUR_PHONE_GAME_MODE_IP --bind YOUR_PI_LOCAL_IP --port 8876 --no-print-key
```

The first run writes a local random `.edge_dashboard_key` next to the script, mode 0600. Keep the key private. Never forward dashboard HTTP ports to the public internet; use a trusted LAN or WireGuard. Cloud pairing requires separate deployment and a callback HTTPS endpoint. This source bundle does **not** include configured systemd service files, ngrok credentials or a verified public installer.

## Quiet Stop

After a successful intentional cloud Stop or timer expiry, the dashboard quietly returns to Standby. The cloud physical-off confirmation is still enforced **before another Start**. A connection failure or undelivered Stop remains a prominent fault. An accepted HTTPS API response is **not** proof that a physical motor stopped.

## Known limits and release gates

1. This candidate passed offline Python tests on the development machine. **No live Pi service or real hardware was touched**, and public v4.5 regression tests still require separate cross-version confirmation on the unified branch.
2. The public v4.5 release documented brief reactivation on Bluetooth reconnect before the recovery Stop succeeded. Physical Stop under link loss cannot be guaranteed.
3. Cloud HTTPS callbacks reflect past events, not continuous device connectivity. Extended cloud sessions need particular caution.
4. The API vendor's distribution terms remain under review; publication to the development branch does not mean a stable, certified or Lovense-endorsed release.
5. This is Edge 2 only; model validation must not select an arbitrary connected device.
6. For Pi deployment, first stage outside the running `private/` tree and preserve an offline/timestamped backup. Do not change the live `edge2-dashboard`, callback, ngrok, Pi-hole, WireGuard, FlightTracker or PS3 services until owner-approved off-body validation.

## Files included

- `edge_dashboard.py`: shared web UI, session engine, explicit runtime profiles, guarded hybrid transport, Quiet Stop.
- `edge2_director.py`: unchanged common Autonomous Director.
- `edge2_https_pairing.py`, `edge2_pairing_ui.py`: HTTPS pairing and QR presentation.
- `https-standard-probe/https_probe.py`: separately authenticated callback helper (not an unattended cloud-control daemon).
- `tests/`: private regression suite plus new unified profile checks.

The older Socket.IO `edge2_cloud_keeper.py` and `controller.py` were intentionally **excluded from the unified runtime package**: they are not active dependencies of the current HTTPS architecture and contain obsolete per-home assumptions. Keep them in archived private history rather than silently reintroducing them.
