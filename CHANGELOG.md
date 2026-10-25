# Changelog

## v4.6 Unified Edition — experimental source (25 October 2026)

- LAN-only is the **public default** (`--profile lan`); Hybrid is explicitly opt-in and its motor commands are disabled until separately authorized.
- Unifies the reviewed private v4.5.7 hybrid implementation and the public LAN controller: Autonomous Director, Quiet Stop, LAN-first hybrid routing, QR/pairing UI and shared read-only pairing setup.
- Runtime cloud enable-flag revocation prevents new cloud motor commands and requires restart to reenable; cloud Stop/recovery remains possible.
- One supported Edge 2, route-pinned fault recovery, mandatory physical-off declaration after cloud Stop.
- Bluetooth reconnection regression: an earlier off-body test produced brief unintended vibration; owner-reported follow-up simulated and off-body retests after the recovery fix did not reproduce it. Physical Stop is still not guaranteed during connection failures.
- 163 offline tests passed on owner's Pi; GitHub Actions run #135 passed Python 3.10–3.13 for consolidated Dev4 before public README/default-profile cleanup.
- Remaining limits: no clean-install/production-service certification, no guarantee of physical Stop under connectivity failures, no Max 2 or multi-device control. External callback and vendor terms require independent review.

## Historical v4.5 LAN-only release (17 October 2026)

The complete original v4.5 LAN-only source, changelog and installation instructions remain in the [`release/v4.5.0-lan-rc1` branch](https://github.com/Otautahi/pulse-director/tree/release/v4.5.0-lan-rc1). Git history is preserved.
