> **Historical v4.5 LAN-only test/design reference.** The current controller is v4.6 with an additional optional Hybrid profile. The detailed observations below describe the earlier v4.5 build; see [v4.6 security and testing](V46_SECURITY_AND_TESTING.md) for current behavior.

# Edge 2 hardware smoke test — v4.5.0 LAN RC1

**Status (updated 17 October 2026):** The original build passed the basic off-body smoke test but **failed Bluetooth reconnection** (persistent unintended vibration). The corrected candidate, subsequently merged into this branch, was retested off-body: Bluetooth reconnection caused **brief resumed vibration followed by automatic Stop**; the dashboard fault latch and acknowledgement worked. Wi-Fi loss/reconnect also stopped motors and recovered without resumed vibration. **Forty offline tests** now pass in CI, including five Stop/Start concurrency tests and malformed API-response validation. The owner ran 39 tests on the Pi before this final response-validation addition. These are owner reports on one Edge 2, not broad physical fail-safe certification. Keep physical shutdown available; do not consider this a production-grade emergency Stop.

## Before testing

- Stop any active session in any other dashboard/controller. **Never run two controllers' motor sessions against the same phone/toy simultaneously.**
- Ensure just **one Edge 2** is connected in Lovense Remote; disconnect Max 2 and any other Lovense devices.
- Enable **Game Mode** in Lovense Remote and note the phone's local IPv4 address. Use a trusted LAN.
- Confirm the published candidate is in its **own directory**, not the existing live installation.
- Do not send IP addresses, access keys, device identifiers or unredacted logs to GitHub or ChatGPT.

## Set up on the Raspberry Pi

If you have not cloned the candidate already:

```bash
cd ~
git clone --branch release/v4.5.0-lan-rc1 --single-branch \
  https://github.com/Otautahi/pulse-director.git pulse-director-lan-test
```

Run the offline tests (40 tests in the updated candidate):

```bash
cd ~/pulse-director-lan-test
python3 --version
python3 -m unittest discover -s tests -v
```

While your private dashboard occupies port `8765`, run the candidate on **port `8766`**. Replace the placeholders with the addresses shown **locally** on your own devices:

```bash
python3 edge_dashboard.py --phone YOUR_PHONE_LAN_IP \
  --bind YOUR_PI_LAN_IP --port 8766
```

Open `http://YOUR_PI_LAN_IP:8766` in a browser on your trusted LAN and enter the candidate's **separately generated** dashboard key. Keep that key private.

> If the port is unavailable, choose another unused LAN-only port. Do not router-forward any dashboard port or expose the plain-HTTP interface publicly.

## Five-minute off-body checklist

- [x] **Detection:** dashboard identifies one connected Edge 2. If it rejects the device model, **stop here**; do not bypass verification.
- [x] **Motor 1:** low-intensity manual setting activates only Motor 1 as expected.
- [x] **Motor 2:** low-intensity manual setting activates only Motor 2 as expected.
- [x] **Stop:** Stop ends motor activity promptly. Keep the physical shutoff accessible.
- [x] **Timeout:** 30-second Autonomous Director session ended automatically; motors stopped. The dashboard's minimum timer setting is 0.5 min (30 seconds).
- [x] **Director:** ran with Confident / High energy / Surprise 4/5 and maximum 5/20; live intent display worked and session expired at 30 seconds.

**Bluetooth interruption warning:** The older 16 October candidate displayed 00:00 yet allowed persistent vibration after reconnect. The updated candidate mitigated this with automatic Stop but still allowed a **brief reconnect vibration**. Only perform deliberately controlled tests off-body at low intensity with the physical power button accessible. A network outage prevents Stop delivery until communication resumes. See [recovery design](RECOVERY_DESIGN.md).

## Observed results — 16 October 2026

The owner cloned the exact public release candidate into a separate test directory, ran all **26 offline tests** successfully on the Pi, and started the LAN dashboard on a separate port. The dashboard recognized the connected Edge 2. The built-in seven-second test operated Motor 1, Motor 2 and both together. A subsequent 30-second Autonomous Director session displayed intent/status changes and ended automatically with both motors stopped. A separate Wave session was stopped early with **STOP ALL MOTORS**, and both motors stopped promptly. These are user-observed pass reports, not independent measurements.

**Wi-Fi loss/recovery — 16 October 2026 (owner reported):** During an off-body Wave session, Wi-Fi was disabled on the phone running Lovense Remote. The owner reported that the motors stopped immediately and **did not restart when Wi-Fi was re-enabled**. Exact dashboard state/error text and stop latency were not independently measured. This result covers one real Wi-Fi interruption scenario, not all possible network outages.

**Bluetooth interruption/reconnect FAILED — 16 October 2026 (owner reported):** The motors stopped immediately when phone Bluetooth was switched off, and the dashboard showed `Connection error: Lovense returned: {'code': 402, 'type': 'OK'}` with `00:00` remaining. **Turning Bluetooth back on unexpectedly restarted vibration (not the previous Wave pattern), without an intentional new Start. The dashboard remained unchanged at its connection-error/00:00 state and did not indicate that the toy was vibrating. The vibration persisted until the owner pressed the dashboard Stop control, which successfully stopped it.** The owner confirmed that this successful manual Stop was issued from the **public LAN test dashboard on port 8766**, not the private dashboard. This is a release-blocking failure: [issue #2](https://github.com/Otautahi/pulse-director/issues/2). After the successful manual Stop, the toy was physically powered off, Game Mode was disabled and the LAN test server was stopped. Do not repeat on-body. The precise cause (phone app, toy firmware, API commands, or another source) is not yet known.

**Not yet validated on hardware:** adversarial concurrent Start/Stop requests, multiple repeated interruptions/timing conditions, other app/firmware combinations, independent physical-stop fallback under outage. Five deterministic concurrent Start/Stop tests passed offline; this is not a physical concurrency guarantee. Passing the smoke test does not establish a guaranteed emergency Stop or full hardware compatibility.

## Additional off-body recovery tests — fixed candidate

**Bluetooth (16 October 2026, owner-reported):** With a low-intensity Wave session active, switching off phone Bluetooth ended the session and triggered Lovense error 402 and a red fault warning. After Bluetooth was restored, the toy **vibrated briefly and then stopped automatically**, without manual Stop. The phone API subsequently acknowledged recovery Stop requests; the user physically checked the toy and confirmed the acknowledgement control cleared the warning. This is one mitigation demonstration, not proof that reconnection is free of unwanted motion.

**Wi-Fi (17 October 2026, owner-reported):** After pulling the updated 39-test build, phone Wi-Fi was disabled during an off-body session. Motors stopped, and red connection-fault warnings appeared. When Wi-Fi returned, motors **stayed stopped**; automatic recovery finished and acknowledging the warning restored controls. The user ran all 39 offline tests successfully on the Pi. This confirms a single controlled LAN fault scenario, not a guaranteed response across all network conditions.

## Finish safely

Press Stop in the web UI, turn the device off, and stop the candidate server with **Ctrl+C**. Your private hybrid installation and its service should remain unchanged.

## How to report the results

Share only a sanitized summary, for example:

```text
LAN RC1 hardware check
- Python version: 3.x
- Device detection: PASS / FAIL
- Motor 1: PASS / FAIL
- Motor 2: PASS / FAIL
- Stop: PASS / FAIL
- 30-second expiry: PASS / FAIL
- Autonomous Director: PASS / FAIL
- Connection interruption (optional): PASS / FAIL / NOT TESTED
- Notes: (no keys, IP addresses, toy IDs or raw logs)
```

Even a passing off-body smoke test does **not** certify a guaranteed emergency stop or comprehensive firmware compatibility. See [Security](SECURITY.md) and the [release checklist](RELEASE_CHECKLIST.md).
