# Contributing to PulseDirector v4.6

Contributions are welcome to this independent experimental Edge 2 controller. The `main` branch contains current LAN and optional Hybrid source. Please create a feature branch and open a PR; include deterministic, **offline-only** tests for control changes. Keep the original `release/v4.5.0-lan-rc1` branch intact as historical source.

Run before opening a PR:

```bash
python3 -m unittest discover -s tests -q
python3 -m py_compile edge_dashboard.py edge2_director.py edge2_https_pairing.py edge2_pairing_ui.py https-standard-probe/https_probe.py
```

Never test new controller logic on-body. Do not relax single-Edge-2 checks, intensity caps, Stop priority, transport pinning, callback-expiry checks or fault acknowledgement. No automatic session restart after connectivity loss.

Do not commit access keys, cloud tokens, pairing QR/images, device IDs, callback secrets, personal IPs, systemd credentials or active-session logs. For issues, share only sanitized text and steps to reproduce. Cloud features must remain optional/disabled by default; no vendor API response should be described as independent confirmation of a physical Stop.

See [security notes](docs/SECURITY.md) and [release gates](docs/RELEASE_CHECKLIST.md).
