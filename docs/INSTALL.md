# Install PulseDirector v4.6 — beginner's guide

PulseDirector is a **free, experimental web controller for one Lovense Edge 2**. It runs on a **Raspberry Pi or Linux computer**; your **phone runs Lovense Remote** and talks to the Edge 2. You open the controls in a web browser. You do **not** need a cloud subscription, Docker or any `pip` packages for the normal local (LAN) installation.

> **Safety first:** the Edge 2 must be **off-body** for setup and initial testing. Software Stop is not a guaranteed physical emergency Stop, particularly if Wi-Fi/Bluetooth/phone communication fails. Keep the toy's physical power control within reach. Only run this dashboard on a **trusted LAN or private VPN**; never port-forward it to the internet.

## 1. Can I install it on my device?

| Device for running the controller | Status |
|---|---|
| **Raspberry Pi 3B+** with Raspberry Pi OS and Python 3.10+ | Tested by the project owner with one Edge 2 |
| Other Raspberry Pi models with Linux and Python 3.10+ | Expected to work from source, but not individually hardware-verified |
| Linux desktop, laptop, mini PC or home server with Python 3.10+ | Source installation supported; Linux CI tests run on Python 3.10–3.13 |
| Windows or macOS | No verified native setup guide or hardware tests yet |
| Android / iPhone by itself | Cannot host the documented Python controller; use the phone for Lovense Remote and browser access |

**Required:** one Edge 2, a phone running **Lovense Remote with Game Mode**, a Raspberry Pi/Linux host with **Python 3.10 or newer and Git**, and a local network where the phone and host can communicate. The Linux host can use **wired Ethernet**, while the phone uses Wi-Fi on the same trusted network.

**Not supported in v4.6:** Max 2, other toy models, or multiple toys simultaneously. Disconnect other toys during testing. Windows, macOS, native phone installation and remote/cloud deployment are not verified beginner installation paths. A separate **experimental LAN-only Docker/Compose setup** is available in [DOCKER.md](DOCKER.md), but is not yet verified with an actual Edge 2 inside a container.

## 2. Prepare your Raspberry Pi / Linux computer

Open a terminal on your Linux host. On Raspberry Pi OS, Debian or Ubuntu, run:

```bash
sudo apt update
sudo apt install -y git python3
python3 --version
```

**Check the last line:** Python must be **3.10 or newer**. If it is older, update to a Linux OS release with an appropriate Python version rather than replacing the OS-managed Python manually.

Download PulseDirector into a **new folder** and run its offline tests:

```bash
git clone https://github.com/Otautahi/pulse-director.git
cd pulse-director
python3 -m unittest discover -s tests -q
```

The tests don't run the motors. If the tests fail, don't proceed to real-device control; see [troubleshooting](TROUBLESHOOTING.md). **Do not clone over an existing PulseDirector installation.**

## 3. Connect the Edge 2 to your phone

1. Keep the Edge 2 **off-body** and its physical power button accessible.
2. Open **Lovense Remote** on your phone and connect **one Edge 2** over Bluetooth.
3. Enable Lovense Remote's **Game Mode** / local API connection. Keep the app available during the session.
4. Make sure the phone's Wi-Fi and the Linux host are on the **same reachable, trusted network** (not an isolated guest network).
5. Find the **phone's local Wi-Fi IP address** in Game Mode or your phone's Wi-Fi network details. It will look something like `192.168.1.50`. Your actual address will be different.

You do **not** install PulseDirector's Python software on the phone. The phone provides Lovense Remote's connection; PulseDirector runs separately on Linux.

## 4. Find your Raspberry Pi / Linux IP address

Back in the Linux terminal, run:

```bash
hostname -I
```

Choose the IP belonging to your **trusted home LAN** (for example, `192.168.1.20`). If more than one appears, use the address your phone can reach; do not choose a public address or an unrelated VPN/container address.

There are **two different IP addresses**:
- `PHONE_IP` = your **phone**, running Lovense Remote Game Mode.
- `LINUX_IP` = your **Raspberry Pi or Linux computer**, running PulseDirector.

## 5. Start PulseDirector

From the `pulse-director` folder, enter the following command. **Replace both placeholders** with the IPs found in steps 3 and 4:

```bash
python3 edge_dashboard.py --profile lan --phone PHONE_IP --bind LINUX_IP --port 8765
```

For example, if the phone is `192.168.1.50` and the Pi is `192.168.1.20`, the command would be:

```bash
python3 edge_dashboard.py --profile lan --phone 192.168.1.50 --bind 192.168.1.20 --port 8765
```

Those addresses are **examples only**; use your own local values.

Leave this terminal **open** while using PulseDirector. The controller runs until you stop it; these steps do **not** install a background service or automatic startup.

## 6. Open the dashboard

On a trusted phone or computer browser connected to your LAN, open:

```text
http://LINUX_IP:8765
```

Replace `LINUX_IP` with your Linux host's actual local IP. PulseDirector prints an **access key in the Linux terminal** at startup. Enter it into the dashboard's login screen.

**Keep the key private.** Never paste it into Reddit, screenshots, GitHub or support logs. For less terminal output, add `--no-print-key` to the launch command; the key is then available locally in `.edge_dashboard_key` inside the project folder (for example, run `cat .edge_dashboard_key` from a second terminal). The file is private and must never be committed.

## 7. Try a short off-body test

1. Confirm the dashboard recognises **one Edge 2**.
2. Use the **lowest intensity**, test **Motor 1** and **Motor 2** independently and make sure the physical response matches.
3. Press **STOP ALL MOTORS** and verify the toy is physically stopped.
4. Try a short timed session and check that it physically stops.
5. If anything behaves unexpectedly, **switch off the toy physically**. Do not treat an API success response as proof that a Stop reached the motors.

An earlier unwanted-vibration-on-Bluetooth-reconnect regression was not reproduced in later simulated and owner-observed off-body retests after the recovery fix. **This does not establish an emergency Stop guarantee during connection loss.** See [security limits](SECURITY.md).

## 8. Stopping and using it again

Press **STOP ALL MOTORS** before shutting down the app, and verify the physical state. In the Linux terminal, press **Ctrl+C** to shut down the dashboard. When you want to run it again, return to the `pulse-director` folder and repeat the command from **step 5**. If your phone's or computer's IP address changes, update the command accordingly.

**Never run two live PulseDirector instances against the same Edge 2.** If port `8765` is already occupied, choose a different unused port; don't overwrite an existing service.

## Optional: preview the dashboard without a toy

From the `pulse-director` folder:

```bash
python3 edge_dashboard.py --profile lan --simulate --port 8876
```

This binds to the **same Linux computer only** (localhost), sends no actual toy commands, and can be opened on that computer at `http://127.0.0.1:8876`. To view a simulator running on a headless Pi from another computer, use an SSH tunnel rather than exposing the simulator publicly:

```bash
ssh -L 8876:127.0.0.1:8876 YOUR_PI_USER@YOUR_PI_HOST
```

Then open `http://127.0.0.1:8876` on the computer running SSH. PuTTY users can set up the equivalent local-port forwarding. Press **Ctrl+C** to stop the simulator.

## Troubleshooting and advanced setup

- **Dashboard won't open:** keep the Linux terminal running, confirm you used the **Linux host's IP**, and make sure the browser is on the same trusted network. If you accidentally bound only to `127.0.0.1`, other devices cannot connect.
- **Edge 2 missing / connection error:** check phone Bluetooth, Lovense Remote, **Game Mode**, both local IP addresses, and guest/client isolation. Turn off other connected toys.
- **Wrong Python version:** `python3 --version` must be 3.10+; use a newer supported Linux installation if necessary.
- **Access key lost:** it stays in the local `.edge_dashboard_key` file; don't share or upload it.
- **Need background startup or updates?** This basic guide starts the process in a terminal. There is **no universal preconfigured systemd service or one-click installer** in the public repository. Do not `git pull` over an active private installation; use a separate checkout, backup and rollback plan.
- **Want remote/cloud use?** The [optional Hybrid guide](HYBRID.md) describes advanced experimental setup. `--profile hybrid` by itself does not enable cloud motor control and is **not** needed for LAN use.

For more help, see [troubleshooting](TROUBLESHOOTING.md), [security limits](SECURITY.md), and the [README](../README.md). This is an unofficial project, not affiliated with Lovense.
