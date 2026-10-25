# PulseDirector v4.6 — public source and deployment checklist

## Completed (software-level checks)

- [x] Consolidated LAN and Hybrid sources in `develop/v4.6-hybrid`; retained v4.5 LAN source in original release branch
- [x] Owner ran 163 offline regression tests on Raspberry Pi 3B+ and targeted Dev4 cloud-revocation tests
- [x] GitHub Actions run #135 passed unit tests, Python compilation and CLI help on Python 3.10/3.11/3.12/3.13
- [x] Offline idle LAN route recovery, active LAN link-loss and cloud fault simulations passed; no real device commands in simulations
- [x] Following the recovery fix, owner-reported simulated and off-body Bluetooth disconnect/reconnect retests did not reproduce the previously observed unwanted vibration (one Edge 2; no general safety certification)
- [x] Limited off-body Edge 2 hardware pilots exercised Motor 1/Motor 2 and automatic Stop; these are not general fail-safe certification
- [x] Public LAN profile refuses cloud pairing; cloud flag absent by default

## Still required for a stable or preconfigured production distribution

- [ ] Fresh clone/installation verified on a second clean supported Pi/Linux host
- [ ] Security review of full repository history and callback/QR deployment; no accidental personal identifiers or secrets
- [ ] Review vendor/API distribution terms and attribution; do not present project as Lovense-endorsed
- [ ] Production Pi upgrade: versioned installer, **PiBackup registration**, backup/rollback and supervised cutover
- [ ] Independent check of Wi-Fi/Bluetooth/cloud failure behavior on supported devices; physical Stop remains unverified during outage
- [ ] No automatic version tag or stable GitHub Release before final acceptance

**Passing offline tests does not guarantee safe physical operation.** Always retain the physical power control, and do not expose dashboard HTTP to the internet.
