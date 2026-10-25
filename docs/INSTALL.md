# Install and operate PulseDirector v4.6

**Experimental controller, not a fail-safe.** One Lovense Edge 2 only. Follow this document on a new Linux / Raspberry Pi OS installation. If upgrading an existing deployment, **do not overwrite its files or service**. Use a separate directory and test first; a project-specific backup/rollback cutover is needed for replacing a running service.

## Requirements

- Python **3.10+**, Git and a Linux/Raspberry Pi OS machine
- A phone running Lovense Remote, and one connected Edge 2
- For LAN mode: local Game Mode enabled on the phone, with Pi-to-phone network reachability
- Trusted LAN/VPN access, and immediate access to the device's physical power control

No pip dependencies, cloud account or HTTPS callback are necessary for the default LAN profile.

## Fresh source checkout, offline tests and simulator

```bash
git clone https://github.com/Otautahi/pulse-director.git
cd pulse-director
python3 -m unittest discover -s tests -q
python3 -m py_compile edge_dashboard.py edge2_director.py edge2_https_pairing.py edge2_pairing_ui.py https-standard-probe/https_probe.py
python3 edge_dashboard.py --profile lan --simulate --port 8876
```

The simulator binds `127.0.0.1` by default, does not contact real devices, and should be stopped with Ctrl+C. If your Pi is headless, use an SSH tunnel from your desktop; for example `ssh -L 8876:127.0.0.1:8876 YOUR_PI_USER@YOUR_PI_HOST`, then open `http://127.0.0.1:8876` locally. PuTTY users can configure an equivalent local SSH tunnel. A per-checkout access key is written beside `edge_dashboard.py`. Don't paste it into tickets, logs or chats.

## Real-device LAN mode, off-body first

1. Keep the Edge 2 **off-body**, fully accessible, and disconnect Max 2 or other toys.
2. Connect the Edge 2 to Lovense Remote, switch on its local **Game Mode**, and note the phone's IPv4 address.
3. Confirm the phone and Pi can communicate on a trusted network. Guest Wi-Fi/client isolation may block local API calls.
4. Start the controller on an appropriate *unused* port using explicit addresses:

```bash
python3 edge_dashboard.py --profile lan --phone YOUR_PHONE_GAME_MODE_IP --bind YOUR_PI_TRUSTED_LAN_IP --port 8765 --no-print-key
```

5. Open `http://YOUR_PI_TRUSTED_LAN_IP:8765` from your own authorized browser and enter the private access key saved in `.edge_dashboard_key` (owner-only file).
6. Verify one Edge 2 is detected, try Motor 1 and Motor 2 separately at minimum intensity, verify manual Stop, and verify a short timed Stop. Never rely on HTTP acknowledgement as proof of physical Stop.

If port 8765 is in use, choose another port. Never run two live controllers for one toy concurrently. Do **not** publish or router-forward a dashboard port; it is HTTP, not HTTPS. Stop immediately at the device if behavior is unexpected.

## Optional Hybrid profile

`--profile hybrid` still prefers local LAN. It is explicitly optional and **does not enable cloud motor commands by itself**. Cloud use requires a separate token, a securely operated HTTPS callback/pairing service, recent authenticated pairing, and a local owner-only opt-in flag. See [HYBRID.md](HYBRID.md). If you don't have these, use LAN mode; the cloud integration is not required for normal operation.

## Updating, services and rollback

A `git pull` changes source files, **not** a safely installed systemd service. Do not pull updates into a live private controller directory. Use versioned release directories, independent test environment and an explicit backup/rollback method; preserve existing `.edge_dashboard_key`, private cloud credentials and callback config outside public source. This repository does not include a preconfigured production service for your network, phone or cloud callback. Scripts in historical development documentation are not general-purpose installers.

The legacy LAN-only edition is available at [`release/v4.5.0-lan-rc1`](https://github.com/Otautahi/pulse-director/tree/release/v4.5.0-lan-rc1). Always verify a fresh checkout separately before promoting production.
