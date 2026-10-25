# PulseDirector v4.6 — Hybrid mode, explained

**New to PulseDirector? Start with the [beginner's LAN installation guide](INSTALL.md).** Hybrid is **optional, advanced and experimental**. Both modes have the same dashboard, 20 patterns, Autonomous Director and individual motor controls. The difference is how they can communicate with your Edge 2.

**Important:** Running PulseDirector with `--profile hybrid` **does not enable cloud motor commands**. The public repository provides code for an experimental HTTPS integration, **not** a hosted pairing service, cloud registration, automatic installer or ready-to-use remote controller.

> **Safety:** A failed Bluetooth, phone, Wi-Fi or cloud connection can prevent a Stop command reaching the Edge 2. An API response does not verify its physical state. Use one Edge 2 **off-body** for initial tests, keep its power button accessible and never expose the web dashboard to the public internet. This software is not a physical emergency Stop.

## 1. LAN versus Hybrid — which should I choose?

| Question | LAN (recommended) | Hybrid (advanced) |
|---|---|---|
| Works with Lovense Remote **Game Mode** on your home network? | Yes | Yes, **preferred** |
| Uses Autonomous Director and manual motor controls? | Yes | Yes |
| Needs your own HTTPS callback and cloud developer token? | **No** | Only for actual cloud use |
| Makes cloud motor commands available automatically? | No | **No — disabled by default** |
| Switches an active session to cloud after a LAN failure? | No | **No — sessions do not silently change routes** |
| Guarantees physical Stop if connectivity fails? | **No** | **No** |

**LAN:** Your Raspberry Pi/Linux computer communicates with Lovense Remote on a reachable phone over your trusted local network. This is the **complete, simplest setup** described in [INSTALL.md](INSTALL.md).

**Hybrid:** It uses that same local route where possible. When local control is unavailable **before a new session**, the software may consider an experimental HTTPS cloud route — but **only** after separate authorization, authenticated pairing and safety checks. Hybrid does **not** automatically make your Edge 2 accessible from anywhere.

**Supported toy:** **One recognized Lovense Edge 2.** Max 2, other models and multiple simultaneous toys aren't supported in v4.6.

## 2. What devices can run Hybrid?

Hybrid is a **mode of the same Python program**, not a different app.

| Host | Status |
|---|---|
| **Raspberry Pi 3B+**, Raspberry Pi OS/Linux, Python 3.10+ | Owner-tested controller host |
| Other Raspberry Pi models with compatible Linux/Python 3.10+ | Expected source compatibility; not individually hardware-verified |
| Linux desktop, mini PC or server, Python 3.10+ | Linux source installation; additional cloud configurations not verified |
| Windows or macOS | Native installation not verified |
| Android/iPhone alone | Not a standalone host; the phone runs Lovense Remote and can access the browser dashboard |

You'll still need a phone and a single Edge 2 for real device control. The normal [LAN setup](INSTALL.md) needs no cloud token or callback service.

## 3. Preview Hybrid safely — no toy required

If you've already downloaded PulseDirector using [INSTALL.md](INSTALL.md), open a terminal **inside the `pulse-director` folder** and run:

```bash
python3 edge_dashboard.py --profile hybrid --simulate --port 8876
```

Open **`http://127.0.0.1:8876`** on that Linux computer. The terminal displays the dashboard access key. For a headless Raspberry Pi, use the [SSH tunnel instructions](INSTALL.md#optional-preview-the-dashboard-without-a-toy) to view it securely from another computer.

This is **simulation only**. It sends **no real device or cloud motor commands**, doesn't need cloud credentials and runs on localhost. Stop with **Ctrl+C**.

**Don't create `.edge_https_cloud_enabled` to preview the UI.** This is the separate live-cloud authorization flag, deliberately absent from the public default installation.

## 4. What would real Hybrid cloud use require?

These are **requirements for experienced operators, not a one-click installation guide**. The public repository does **not** supply a verified end-to-end deployment for an internet-reachable HTTPS pairing callback.

1. **Install and test LAN first** using [INSTALL.md](INSTALL.md). Use one Edge 2, off-body and low intensity, and verify Stop physically.
2. Obtain **your own permitted Lovense developer API access and token**, subject to applicable API/developer terms. Open-source licensing does not grant third-party API permissions; see [issue #4](https://github.com/Otautahi/pulse-director/issues/4).
3. Operate **your own secured HTTPS callback/pairing service** with per-installation authentication. The repository's `https-standard-probe/https_probe.py` is **reference/prototype code**, not a public hosted endpoint, TLS deployment, or automatic setup.
4. Verify **authenticated pairing for exactly one Edge 2**, with private configuration and owner-only permissions. A pairing callback is a record of an **earlier event**, not a live Bluetooth heartbeat.
5. Independently review the **experimental live cloud enable gate** and carry out careful off-body failure/Stop testing. The owner-only authorization flag is **absent by default**, and simply choosing Hybrid or seeing a successful API response does not enable or validate physical control.

**If any of these are missing, use LAN mode.** Do not copy another person's cloud token, callback address, UID, QR code or pairing configuration.

A **private VPN** can help you reach the *browser dashboard* remotely, but that is **not the same** as the Lovense HTTPS motor route. A VPN to your Pi does not by itself make an away-from-home phone's local Game Mode API reachable. Never port-forward PulseDirector's HTTP dashboard to try to enable cloud.

## 5. What the software's cloud safeguards actually do

- **LAN-first:** a new session first checks for the recognized Edge 2 over the local phone Game Mode route.
- **Cloud activation is separately gated:** private developer token, verified pairing, and a valid owner-owned `.edge_https_cloud_enabled` flag are required for experimental cloud motor commands.
- **Pairing checks and Stop-only preflight:** before a cloud Start, the controller checks for a recent authenticated callback and requests a cloud **Stop-only** response. This verifies *server acceptance*, **not** physical motor state or live connection.
- **No mid-session route switching:** LAN and cloud sessions pin their route. If it fails, PulseDirector attempts Stop/recovery and blocks automatic resumption rather than silently switching routes.
- **Revocation:** removing/invalidating the cloud authorization blocks new cloud motor commands in that running process; Stop/recovery attempts remain allowed. Re-creating the flag does **not** re-arm the same process.
- **Physical-off acknowledgement:** after a cloud Stop, the user must acknowledge physically switching off the Edge 2 before another cloud Start.

These are **software-level safeguards, not a hardware fail-safe**. Network failures can delay or prevent Stop, and a cloud API `200` response is not confirmation that the toy stopped.

## 6. Technical options (for existing private installations)

| Setting | What it means |
|---|---|
| `--profile lan` | Default, local Game Mode only; no cloud token or pairing access |
| `--profile hybrid` | Selects LAN-first Hybrid software/UI; **does not enable cloud motor commands** |
| `PULSEDIRECTOR_CLOUD_TOKEN_FILE` | Optional private path for your own developer token |
| `.edge_cloud_token` | Default local cloud token file path for live Hybrid if no override is supplied |
| `PULSEDIRECTOR_HTTPS_PROBE_DIR` | Optional separately operated pairing-helper directory, read-only to a shared helper |
| `.edge_https_cloud_enabled` | Separate owner-only opt-in to live experimental cloud motor commands; **absent by default** |

All private credentials and pairing configuration should be restricted to their owner. Never put your dashboard access key, callback URL, UID, developer token, QR code or unredacted logs in GitHub/Reddit. **This table documents options, not instructions to switch on experimental cloud control without a reviewed setup.**

## 7. Frequently asked questions

**Do I need Hybrid for the Autonomous Director?** No. LAN mode includes the full Director and pattern library.

**Can I just install Hybrid and control Edge 2 away from home?** No. The optional cloud motor route requires your own separately configured, authenticated HTTPS callback, token, pairing and explicit opt-in. No hosted cloud setup is supplied.

**Is the dashboard itself an HTTPS cloud service?** No. The browser dashboard uses HTTP and must stay on a trusted LAN or carefully configured private VPN; the separate HTTPS callback infrastructure is not the browser UI.

**Can it guarantee Stop if the phone disconnects?** No. A Stop can be blocked by connectivity failure. Use the toy's physical power button if necessary.

**What should a first-time user do?** Follow [INSTALL.md](INSTALL.md), use LAN mode and keep experimental cloud control disabled.

---

Further reading: [Installation](INSTALL.md) · [Security](SECURITY.md) · [Troubleshooting](TROUBLESHOOTING.md) · [v4.6 testing](V46_SECURITY_AND_TESTING.md). PulseDirector is an independent community project, not affiliated with or endorsed by Lovense.
