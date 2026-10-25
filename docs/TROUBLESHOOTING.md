# Troubleshooting PulseDirector v4.6

## Dashboard doesn't open

The app binds to **127.0.0.1** by default. On a headless Pi, use an SSH tunnel, or pass `--bind YOUR_PI_TRUSTED_LAN_IP` and browse to `http://YOUR_PI_TRUSTED_LAN_IP:PORT` from a trusted device. The default port is 8765; use 8876 for separate simulation. Never port-forward this HTTP UI to the public internet.

If the browser displays **Failed to fetch**, refresh the page fully after restarting the server, check the correct bind address/port, and check that the access key is current. The dashboard key is stored in `.edge_dashboard_key` beside `edge_dashboard.py` and should not be shared in reports.

## Edge 2 not detected on LAN

Confirm Lovense Remote is running with **Game Mode** enabled, the phone and Pi can reach each other over the LAN, and the `--phone` IP is the *phone's* Game Mode address. Guest isolation, VPN routing and Wi-Fi disconnection may block access. Disconnect unsupported toys; this version requires **exactly one recognized Edge 2**. Don't override validation to force a Max 2 or ambiguous device.

## Hybrid cloud status is unclear

Hybrid is **optional**. `--profile hybrid` enables the diagnostics/pairing interface, but it does not automatically permit cloud motor commands. A token, authenticated callback/pairing and an explicit owner-only local enable flag are required. Old callback timestamps do not establish current app connectivity. See [HYBRID.md](HYBRID.md).

If cloud control was disabled or the flag removed while running, **restart the controller** after deliberate reconfiguration; putting the flag back cannot re-arm the same process. Cloud Stop API acceptance does not prove the device physically stopped; follow physical power-off prompts.

## Fault latch or disconnect

A connection failure causes Stop attempts and may lock new sessions. Do not try to bypass the latch. Keep the device off-body for testing, power off physically when necessary, allow route-pinned recovery Stop attempts, then acknowledge only as the UI instructs. An earlier off-body Bluetooth reconnection test showed brief unintended vibration; after the recovery fix, the owner reported that simulated and off-body retests did **not** reproduce it. Bluetooth/Wi-Fi failure can still prevent Stop delivery, and behaviour under other failures is not guaranteed.

## Python tests fail

Run `python3 --version` (requires 3.10+) and `python3 -m unittest discover -s tests -v` from the **root of the repository**. Do not run multiple live copies against the same toy. If reporting a bug, include only sanitized error text without IPs, QR codes, tokens, access keys, device identifiers or live session logs.
