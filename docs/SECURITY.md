# PulseDirector v4.6 — security, privacy and physical control limits

**PulseDirector controls a physical motor device and has no independent physical Stop guarantee.** The dashboard is intended for a trusted LAN or private VPN only. It uses **HTTP**, not TLS, with a generated shared access key; do not port-forward its port, bind it to a public interface, or use it on an untrusted LAN. Restrict access to authorized clients.

## Files, tokens and transport

- `.edge_dashboard_key` is generated locally and must remain owner-only. The key is independent of cloud pairing and must never be committed, logged or shared.
- The default `--profile lan` does **not** read cloud tokens or expose cloud pairing. It contacts a local phone's Game Mode endpoint only.
- `--profile hybrid` is optional and does not automatically enable cloud motor commands; token, authenticated pairing and a separate owner-only activation flag are required. The flag is revoked for the running process if removed or made unsafe. STOP remains available in recovery.
- Treat cloud token, callback config, UID, authentication state, pairing QR and logs as sensitive. Use `PULSEDIRECTOR_CLOUD_TOKEN_FILE` and `PULSEDIRECTOR_HTTPS_PROBE_DIR` for separate privately stored data where needed; never publish these values or the actual callback URL.
- HTTPS Cloud API transport is not proof that your *browser dashboard* is secure for public exposure. Server acknowledgement is not proof of physical motor movement or Stop. A pairing callback is historical, not a live heartbeat.

## Physical limits

- Supports only one connected, recognized Edge 2. Max 2/multiple toy control is not implemented.
- Stop, short command durations, fault latches and recovery are best-effort safeguards. Network/Bluetooth failures can delay or block Stop; physical motor state cannot be guaranteed during an outage. An earlier off-body LAN test observed brief vibration on Bluetooth reconnection before automatic Stop. Following recovery fixes, the owner reported simulated and off-body Bluetooth disconnect/reconnect retests on one Edge 2 **without recurrence of the unwanted vibration**. This is a regression result, not a general physical Stop guarantee; unexpected motion on reconnection remains a risk under untested conditions.
- For cloud Stop or cloud recovery, physically switch off the device before acknowledging to rearm. Always keep immediate access to a real power button/physical disconnect; test off-body at low intensity before any new release.
- Tests and an API `200` do not constitute physical safety certification or a guarantee across devices/firmware.

## Responsible disclosure and terms

Never submit screenshots or issues containing private data. `.gitignore` does not remove data committed in earlier history; leaked tokens must be revoked/rotated.

This independent project is not affiliated with or endorsed by Lovense. MIT licenses this project's own code but does not supersede third-party developer agreements, API access conditions, trademarks or vendor material. An open question about API-publication applicability is tracked in [issue #4](https://github.com/Otautahi/pulse-director/issues/4); users must comply with their own applicable terms.
