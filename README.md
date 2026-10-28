# PulseDirector — control your Lovense Edge 2 from a browser

**Raspberry Pi or Linux computer? You can get started with a few copy-and-paste terminal commands — no programming required.**

PulseDirector is a **free, open-source, self-hosted Edge 2 controller** with separate control for both motors, a library of 20 modes, adjustable intensity and timers, and an **Autonomous Director** that plans changing patterns. Use the dashboard from a phone or computer browser.

**The standard LAN setup needs no subscription, cloud developer token, Docker or extra Python `pip` packages.** Your phone runs Lovense Remote; your Raspberry Pi or Linux computer runs PulseDirector. Hybrid/cloud features are optional and experimental.

**[Beginner-friendly installation guide](docs/INSTALL.md)** · **[Try a simulator without a toy](docs/INSTALL.md#optional-preview-the-dashboard-without-a-toy)** · **[Docker (experimental)](docs/DOCKER.md)**

> **Important safety note:** This is an experimental controller, **not a physical emergency-stop system**. For initial tests, keep the Edge 2 **off-body**, start at low intensity and keep its physical power button within reach. A lost Bluetooth/Wi-Fi/phone connection can prevent Stop from reaching the device. Never expose the HTTP dashboard to the public internet.

## Quick start — Raspberry Pi OS / Debian / Ubuntu (LAN)

**What you need:** A Raspberry Pi or Linux computer with **Python 3.10+**, Git, one **Lovense Edge 2**, and a phone with **Lovense Remote** and **Game Mode**, connected on a trusted, mutually reachable local network. You do **not** need to configure Hybrid or Docker.

**1. Open a terminal on your Pi/Linux computer.** If your Pi is headless, connect to it using SSH. Run:

```bash
sudo apt update
sudo apt install -y git python3
python3 --version
```

Make sure the Python version displayed is **3.10 or newer**.

**2. Download PulseDirector and run its offline checks.** Run these commands in the **same terminal**:

```bash
git clone https://github.com/Otautahi/pulse-director.git
cd pulse-director
python3 -m unittest discover -s tests -q
```

The test run should finish with **`OK`** (the test count can change). It does not control a real toy. If tests fail, stop here and use the [troubleshooting guide](docs/TROUBLESHOOTING.md).

**3. Pair the Edge 2 with Lovense Remote** on your phone, enable **Game Mode**, and note your **phone's local Wi-Fi IP address**. Keep the toy off-body. On your Pi/Linux computer, run `hostname -I` to find its **LAN IP address**. These are **two different IPs**; don't use isolated guest Wi-Fi or a public address.

**4. Start the LAN controller.** Replace `PHONE_IP` and `LINUX_IP` below with your actual phone and Pi/Linux LAN addresses:

```bash
python3 edge_dashboard.py --profile lan --phone PHONE_IP --bind LINUX_IP --port 8765
```

**5. Open `http://LINUX_IP:8765`** on a browser connected to your trusted home network. Enter the private access key shown in the terminal. Your dashboard should appear; confirm that it detects **one Edge 2** before trying each motor at low intensity **off-body**. Check manual Stop and a short timed Stop. Keep the terminal running; press **Ctrl+C** to exit when the device is physically stopped.

**Rather try it without a toy?** From the `pulse-director` directory run `python3 edge_dashboard.py --profile lan --simulate --port 8876`. This is a **localhost-only** preview with no real motor commands. If running on a headless Pi, use the [SSH tunnel instructions](docs/INSTALL.md#optional-preview-the-dashboard-without-a-toy) to view it.

**Stuck or new to Linux?** The [step-by-step beginner installation guide](docs/INSTALL.md) explains where to enter each command, which IP is which, what output to expect and common connection problems.

**Have you tried it?** [Report your first result — success or problem](https://github.com/Otautahi/pulse-director/issues/new?template=first-time-tester.yml). Even a quick confirmation that it installed helps.

[![Offline tests](https://github.com/Otautahi/pulse-director/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Otautahi/pulse-director/actions/workflows/tests.yml) · [MIT source licence](LICENSE) · [Security and limitations](docs/SECURITY.md)

## See what the dashboard looks like

These are **static previews rendered from the actual v4.6 interface**, with the Edge 2 disconnected and no session active. No pairing codes, access keys, or private network details are shown.

### Desktop dashboard

![PulseDirector desktop dashboard, disconnected preview](docs/screenshots/01_desktop_dashboard.png)

### Pattern library and Autonomous Director

![PulseDirector pattern library](docs/screenshots/02_pattern_library.png)

![PulseDirector Autonomous Director settings](docs/screenshots/03_autonomous_director.png)

<details>
<summary>Mobile dashboard previews</summary>

<p>
  <img src="docs/screenshots/04_mobile_dashboard.png" width="300" alt="PulseDirector mobile dashboard preview">
  <img src="docs/screenshots/05_mobile_director.png" width="300" alt="PulseDirector mobile Autonomous Director settings">
</p>
</details>

## Where does it run?

| What you have | Installation status |
|---|---|
| **Raspberry Pi 3B+** running Raspberry Pi OS / Linux with Python 3.10+ | **Owner-tested** with one Edge 2 |
| **Other Raspberry Pi models** with a suitable Linux OS and Python 3.10+ | Intended to work; not individually hardware-tested |
| **Linux PC, mini PC or server** with Python 3.10+ | Supported source setup; physical Edge 2 testing has focused on the Pi |
| **Windows or macOS computer** | Native installation **not verified or documented** |
| **Android or iPhone alone** | **Not a standalone phone app.** The phone runs Lovense Remote; open the PulseDirector dashboard in a browser |

## LAN or Hybrid? Start with LAN

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

## Tried PulseDirector? Tell us how it went

**Even a quick "it worked" helps.** If you tried installing PulseDirector, I'd love to hear whether the instructions made sense, whether your Edge 2 connected, or exactly where you got stuck.

**[Share your first-time test result](https://github.com/Otautahi/pulse-director/issues/new?template=first-time-tester.yml)** · [See all issues and feature requests](https://github.com/Otautahi/pulse-director/issues)

No detailed logs are needed for a success report. For problems, mention your **Pi/Linux OS**, Python version and what happened — **never post dashboard keys, cloud tokens, pairing codes, personal IPs, device IDs or private logs**.

## Safety limitations

**The controller cannot guarantee physical Stop during loss of Bluetooth, Wi-Fi, phone connectivity or cloud access.** A successful API response does not verify motor state. An earlier off-body LAN test observed *brief renewed vibration on Bluetooth reconnection* before recovery Stop. After recovery changes, the owner retested Bluetooth disconnect/reconnect in simulation and with the Edge 2 off-body; **the unintended vibration was not observed again in those tests**. This supports the software regression fix, but it does not prove physical Stop under every failure condition. Keep the physical power button reachable and power off if behavior is unexpected.

LAN/Hybrid sessions pin the transport used to start a session; a failure latches a fault and blocks auto-resume. Cloud Stop requires separate physical-off acknowledgment before another Start; cloud callbacks indicate past pairing, not live device heartbeat. Testing was performed with simulated faults and limited owner-observed off-body tests on one Edge 2, **not** independently certified across devices or firmware.

## Support future device development

PulseDirector is free and open-source. If you'd like to help expand support to other Lovense devices, you can optionally gift a device through my [Lovense Wishlist](https://www.lovense.com/wish-list/3h7t6t3).

**Devices received as gifts will be given priority for development and real-hardware testing.** Having the device available makes it possible to investigate compatibility and test changes safely. Priority does not guarantee support or a particular release date; technical feasibility and safety testing still matter.

No sponsorship is required to use PulseDirector.

## Install, help and history

- [Installation and startup](docs/INSTALL.md) · [Security and deployment](docs/SECURITY.md) · [Hybrid mode explained and safe preview](docs/HYBRID.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md) · [Release checklist](docs/RELEASE_CHECKLIST.md) · [Changelog](CHANGELOG.md)
- The original **v4.5 LAN-only edition** is preserved in the [`release/v4.5.0-lan-rc1` branch](https://github.com/Otautahi/pulse-director/tree/release/v4.5.0-lan-rc1). The legacy branch and Git history are retained; this v4.6 tree is the unified current codebase.

The MIT licence covers this project's own source. Lovense API/developer terms and trademark rights are separate; see the [licensing caveat](docs/SECURITY.md) and [issue #4](https://github.com/Otautahi/pulse-director/issues/4). This source release does not imply vendor endorsement or permission beyond those terms.

