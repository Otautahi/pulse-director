> **Historical v4.5 LAN-only test/design reference.** The current controller is v4.6 with an additional optional Hybrid profile. The detailed observations below describe the earlier v4.5 build; see [v4.6 security and testing](V46_SECURITY_AND_TESTING.md) for current behavior.

# Connection-failure Stop recovery — experimental design

**Status: prototype, with a first successful off-body reconnection test (16 October 2026).** This is not a physical Stop guarantee. See [issue #2](https://github.com/Otautahi/pulse-director/issues/2) for the original persistent vibration on Bluetooth reconnect and the fix follow-up. **The updated build still allowed a brief reconnect vibration before automatically stopping it.** Further testing, review and owner approval are required before merging or release.

## Behaviour implemented in this release candidate

1. An active session sends short, time-bounded LAN commands. When a motor request fails (including Lovense error 402 during Bluetooth loss, or Wi-Fi/phone unreachable), the worker invalidates the session generation and **attempts Function/Stop immediately**.
2. If the phone or toy is unavailable, the Stop call can fail. The controller **latches the fault**, retains a **Stop pending** flag, and displays a prominent warning that the **physical motor state is unknown**, regardless of the dashboard's 00:00 timer.
3. A separate recovery worker checks phone/Game Mode and whether **exactly one Edge 2** is connected at about **one-second intervals** while Stop is pending. Only after the device is reported connected does it issue a new **Function/Stop**.
4. The recovery worker attempts three successful Stop acknowledgements at separate intervals to help clear delayed app/device command state. If connectivity disappears or an attempted Stop fails, it resets this acknowledgement count and keeps retrying while the server runs.
5. The **Start**, **Manual Start** and **Motor Test** endpoints refuse new sessions while a fault is latched, including if the browser is bypassed. Once three phone-API Stop acknowledgements have been received, the owner must physically check the toy and explicitly acknowledge the fault to unlock controls.
6. The prominent Stop button remains usable even while the dashboard reports idle or the recovery worker is active, allowing an immediate additional Stop attempt whenever the phone can receive it.
7. While a session is active the telemetry worker checks device connection roughly every two seconds (instead of every 20 seconds). A motor command failure usually triggers detection even sooner.

## Concurrent Stop priority

An offline regression reproduced an additional race: if an explicit Stop arrived while a Start or motor-test request was waiting for the device-readiness response, the older code could subsequently start the session despite that Stop. The fix records a Stop epoch before validation and cancels pending Start/Test requests if any explicit Stop, connection-failure Stop, timeout Stop or shutdown occurred in the meantime. Internal pattern changes issue their own Stop without hiding a separate user's Stop. Five deterministic tests cover both idle and active pattern-switch cases; a later fresh Start remains possible after Stop, provided the fault latch permits it. These tests do not substitute for physical or adversarial concurrency validation.

## Important limitations

- **No Stop can be delivered while the phone is unreachable or Bluetooth is disconnected.** A resumed command may activate motors before the first post-reconnect Stop reaches the toy. Automatic retry is mitigation, not prevention of the initial burst.
- A 200 response from Lovense Remote confirms *phone-API acknowledgement* only, not an independently measured change of physical motor state. Even three successful requests cannot certify physical stop.
- The toy may reconnect without the app immediately reporting a connected Edge 2. The one-second check is an approximate software polling interval, not a promised hardware reaction deadline.
- The controller cannot detect whether an unrelated app, Lovense firmware, or phone UI itself starts vibration. Hard power-off of the toy is the independent safety action.
- The fault/recovery worker only runs while this Python process is alive. A power outage, process crash or forced kill can prevent retries.
- This proof-of-concept uses no cloud API, remote access, or private device identifiers. It must remain separate from the owner's production/hybrid installation.

## Validation requirements

- [x] Simulated error 402 + failed Stop, then Bluetooth reconnect: repeated STOP only, never a stale vibration command (offline)
- [x] Simulated Wi-Fi loss and recovery: repeated STOP and locked session (offline)
- [x] Phone reachable while Bluetooth disconnected: no false Stop acknowledgements (offline)
- [x] Phone reporting connected but refusing Stop: no false recovery (offline)
- [x] Normal manual Stop continues to work (offline)
- [x] Confirm full GitHub Actions test suite on Python 3.10, 3.11, 3.12 and 3.13 (**40 offline tests**, including five concurrent Stop/Start regressions and one malformed-response safety test)
- [x] First off-body check on actual Edge 2, at low intensity, with power button accessible (owner-reported, 16 October 2026)
- [x] First Bluetooth disconnect/reconnect: error 402 triggered fault lock; after reconnect the toy briefly vibrated, then stopped **automatically** with no manual Stop; dashboard reported phone-API Stop accepted (owner-reported)
- [x] Verify owner acknowledgement: once API recovery was reported, clicking **Acknowledge after checking physical device** cleared the red warning and returned the dashboard to normal (owner-reported, 16 October 2026)
- [ ] Repeat controlled off-body failure/reconnection tests under varied timing
- [x] Test concurrent Stop vs in-progress Start, motor Test and pattern-switch validation using deterministic offline races (5 new tests). An explicit Stop now invalidates pending sessions, so a stale Start cannot reactivate motor commands
- [x] **Phone Wi-Fi failure/reconnect on updated candidate** — owner-reported on 17 October 2026: motors stopped on Wi-Fi loss; red connection-fault warnings appeared; after restoring Wi-Fi the motors remained stopped, automatic Stop recovery completed, and acknowledgement restored controls
- [ ] Test additional phone/app/firmware variability and further real-world connection failures before release

### Observed physical behaviour — 16 October 2026

The owner reported that the Edge 2 was detected by the isolated candidate test dashboard on port 8766 and, when Bluetooth was disabled during a Wave session, the fault warning appeared with automatic Stop pending. Following Bluetooth reconnection, the toy **vibrated briefly and then stopped automatically**. The dashboard later showed Stop had been accepted by the phone API and enabled the acknowledgement button. This was **one successful off-body physical test**, not a quantitative stop-latency measurement. The owner subsequently confirmed that clicking the acknowledgement button cleared the red warning and returned the dashboard to normal. This verifies the observed UI acknowledgement flow, but does not independently prove physical motor state or test restarting a motor session.

### Observed Wi-Fi recovery — 17 October 2026

Following the updated concurrent Stop/Start fix (39 offline tests passed on the owner's Raspberry Pi before the final response-shape regression was added), the owner conducted another low-intensity off-body Wave session using the isolated public candidate test dashboard on port 8766. Disabling phone Wi-Fi stopped the motors, and both red connection-fault warnings appeared. On reconnection, the motors **remained stopped**, recovery completed successfully, and the acknowledgement button restored the dashboard to normal. These results were reported by the owner, not measured independently. No brief vibration on Wi-Fi reconnect was reported.

This is an independent project and not affiliated with Lovense. Vendor API compatibility and redistribution terms remain under review.
