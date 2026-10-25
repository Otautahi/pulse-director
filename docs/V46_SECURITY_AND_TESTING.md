# v4.6 — security boundaries and verification

## Scope

The default **LAN-only** profile uses the Lovense Remote phone Game Mode API on a trusted LAN. The **Hybrid** profile is optional and allows guarded, experimental cloud use only when separately configured and enabled. Neither profile is a physical fail-safe. The web dashboard itself uses a local shared key over HTTP, and must never be publicly port forwarded.

No dashboard keys, cloud tokens, pairing status, QR images, private callback addresses, session logs or live systemd/ngrok credentials belong in the source tree or Git history. `.gitignore` alone is insufficient to sanitize earlier Git commits.

## Verified software behavior

- Stop takes priority over delayed Start/Test and pattern switching; stale generation commands must not restart output.
- Exactly one recognized Edge 2 is required; Max 2 and other toys are not supported.
- Active transport is pinned to its initial route. Link failures latch faults, issue Stop/recovery attempts, and prevent automatic resumption.
- Cloud activation is opt-in, checked at runtime, and revoked for the process if the owner-only activation flag is removed or compromised; new cloud motor commands are blocked, while Stop requests remain possible.
- Cloud callbacks are historical pairing records, **not** a live heartbeat. A cloud server response never verifies actual motor inactivity. Physical power-off is required before cloud rearm.
- The simulation profile must never contact device or vendor APIs.

## Evidence (25 October 2026)

- 163 offline regression tests passed on the owner's Raspberry Pi 3B+, including six Dev4 runtime-gate tests.
- A distinct GitHub review checkout passed all 163 offline tests, with 12 repeated pattern-switch checks.
- GitHub Actions workflow #135 for consolidated Dev4 commit `7b51511` passed all configured jobs on Python 3.10, 3.11, 3.12, 3.13.
- Owner-observed limited off-body Motor 1, Motor 2, manual and timed Stop pilots. The owner also reported follow-up Bluetooth disconnect/reconnect tests, both simulated and with one Edge 2 off-body, in which the earlier brief unintended vibration did **not** recur after the recovery changes. LAN active fault and HTTPS fault scenarios were also simulated or mocked. No claim of safe motor behavior during all real network failures.

## Open release risks

Fresh installation portability, private backup/rollback integration, callback security, vendor terms and safe production cutover remain subject to review. Keep cloud disabled until properly configured and assessed. This code is an **experimental controller**, not a certified safety mechanism.
