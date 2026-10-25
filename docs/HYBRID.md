# Optional v4.6 Hybrid (LAN + experimental HTTPS Cloud)

The **default public setup is LAN-only**. Hybrid is advanced, experimental, and requires a separate authenticated callback/pairing service. This repository does not provide a hosted callback endpoint, per-user cloud registration or an unattended cloud installer. Never copy another person's callback URL, QR code, UID or cloud credentials into your setup.

## What `--profile hybrid` does

- Prefers the phone's local Game Mode connection; idle route selection can consider a validated Cloud pairing when LAN is unavailable.
- Reads a configured token only for live Hybrid mode. It does not fetch any cloud token in LAN-only profile or during simulations.
- Enables the paired cloud route for motor control **only** with a locally validated owner-only `.edge_https_cloud_enabled` flag, separately configured token and authenticated pairing; the flag is intentionally **absent by default**.
- Disabling this flag at runtime stops the cloud session and prevents new cloud motor commands. Stop/recovery commands remain allowed. Recreating the flag does not rearm cloud in that running process.
- Does **not** guarantee physical motor Stop, delivery or live connection. Vendor server acceptance and historical callbacks are not device heartbeats.

A routine cloud Stop and a faulted cloud Stop both retain the physical-power-off requirement before another cloud Start. In a connection failure, automatic cloud recovery may be delayed or impossible; **manually power off the device** rather than relying on a remote Stop.

## Private configuration and diagnostics

With `--profile hybrid`, the program can read a token from `.edge_cloud_token` beside the dashboard or the `PULSEDIRECTOR_CLOUD_TOKEN_FILE` environment-variable path. Tokens must be local regular files with owner-only access; never put token values into commands, screenshots, GitHub, commits or logs. A previously configured pairing helper can be referenced read-only through `PULSEDIRECTOR_HTTPS_PROBE_DIR`; the dashboard must not write into someone else's pairing store. The repository's `https-standard-probe/https_probe.py` is source code for a pairing callback helper, **not** a preconfigured publicly accessible service.

**Do not create the cloud-enable flag just to see the Hybrid UI.** Use a no-device simulator:

```bash
python3 edge_dashboard.py --profile hybrid --simulate --port 8876
```

Production cloud setup should follow your own vendor authorization and audited TLS/callback deployment. Do not publish a public HTTP dashboard to make the remote motor API work; these are separate transports.

See [SECURITY.md](SECURITY.md) for cloud limitations and [v4.6 safety testing](V46_SECURITY_AND_TESTING.md) for verified software-level regression checks. Original private Pi pairing service configuration is intentionally not included in this public repository.
