# PulseDirector v4.6 — Edge 2 LAN & Hybrid controller

**Experimental / community project — not a certified physical safety device.** An independent, free, self-hosted browser controller for **one Lovense Edge 2** on Linux / Raspberry Pi OS, with a local Game Mode (LAN) profile and an **optional experimental** HTTPS Cloud integration. It is not affiliated with Lovense.

[![Offline tests](https://github.com/Otautahi/pulse-director/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Otautahi/pulse-director/actions/workflows/tests.yml) · [MIT source licence](LICENSE) · [Security and limitations](docs/SECURITY.md)

## Profiles — LAN is the default

| | LAN (default) | Hybrid (opt-in) |
|---|---|---|
| Phone Game Mode over trusted LAN | Yes | Preferred when available |
| Lovense HTTPS API motor commands | **No** | Experimental, **disabled by default** |
| Cloud pairing / QR controls | Hidden/blocked | Available only with separate configuration |
| Personal cloud token required | No | Only when configuring cloud transport |
| Cloud response proves physical Stop | No | **No** |

- Start in LAN mode with `--profile lan` (or omit `--profile`); no cloud token is loaded, and the cloud pairing API is unavailable.
- `--profile hybrid` selects a LAN-first controller with cloud diagnostic/pairing functionality. It does **not** authorize cloud motor commands. Cloud use additionally requires separately configured credentials, verified pairing and an owner-controlled enable flag. Runtime flag removal revokes new cloud motor commands; Stop remains permitted, and re-enabling requires a fresh process.
- Both profiles share the motor-pattern engine and rule-based **Autonomous Director** (20 modes, manual independent motor controls, adjustable intensity, session timers, and Stop/recovery safeguards).

**Supported device:** a *single* reported Edge 2. Max 2, other toys and simultaneous multi-device operation are **not implemented**. The program refuses ambiguous, unsupported or multiple reported devices.

## Quick start (Linux / Raspberry Pi OS, Python 3.10+)

Use a *new, separate directory* and avoid overwriting a running controller:

```bash
git clone https://github.com/Otautahi/pulse-director.git
cd pulse-director
python3 -m unittest discover -s tests -q
python3 edge_dashboard.py --profile lan --simulate --port 8876
```

Simulation is loopback-only (`127.0.0.1:8876`) and sends no real motor commands. From a headless Pi, connect with an SSH tunnel. To test the UI's optional Hybrid layout without real cloud access, use `--profile hybrid --simulate --port 8876` instead.

For live **LAN-only** use, after reading the [installation guide](docs/INSTALL.md), connect *one* Edge 2 in Lovense Remote's Game Mode, keep the device **off-body** and start at the lowest level:

```bash
python3 edge_dashboard.py --profile lan --phone YOUR_PHONE_GAME_MODE_IP --bind YOUR_PI_TRUSTED_LAN_IP --port 8765 --no-print-key
```

The web dashboard uses HTTP with a locally generated access key (`.edge_dashboard_key` beside the script, owner-only file). It is **not internet-safe**: **never port-forward** the web UI. Use a trusted LAN or carefully configured private VPN only. Do not publish access keys, IP addresses or pairing tokens.

For HTTPS/cloud background, see [Hybrid setup and limits](docs/HYBRID.md). Hybrid needs separately operated callback/pairing infrastructure; this repository does **not** automatically deploy or enable it.

## Safety limitations

**The controller cannot guarantee physical Stop during loss of Bluetooth, Wi-Fi, phone connectivity or cloud access.** A successful API response does not verify motor state. A previous off-body LAN test observed *brief renewed vibration on Bluetooth reconnection* before an automatic recovery Stop. Keep the physical power button reachable and physically stop/power off if behavior is unexpected. Never assume remote Stop is a hardware fail-safe.

LAN/Hybrid sessions pin the transport used to start a session; a failure latches a fault and blocks auto-resume. Cloud Stop requires separate physical-off acknowledgment before another Start; cloud callbacks indicate past pairing, not live device heartbeat. Testing was performed with simulated faults and limited owner-observed off-body tests on one Edge 2, **not** independently certified across devices or firmware.

## Install, help and history

- [Installation and startup](docs/INSTALL.md) · [Security and deployment](docs/SECURITY.md) · [Hybrid Cloud limitations](docs/HYBRID.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md) · [Release checklist](docs/RELEASE_CHECKLIST.md) · [Changelog](CHANGELOG.md)
- The original **v4.5 LAN-only edition** is preserved in the [`release/v4.5.0-lan-rc1` branch](https://github.com/Otautahi/pulse-director/tree/release/v4.5.0-lan-rc1). The legacy branch and Git history are retained; this v4.6 tree is the unified current codebase.

The MIT licence covers this project's own source. Lovense API/developer terms and trademark rights are separate; see the [licensing caveat](docs/SECURITY.md) and [issue #4](https://github.com/Otautahi/pulse-director/issues/4). This source release does not imply vendor endorsement or permission beyond those terms.
