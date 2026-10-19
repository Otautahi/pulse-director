# v4.6 unified hybrid — security and verification gates

## Source control

Do not commit any `.edge_dashboard_key`, `.edge_cloud_token`, `.edge_https_cloud_enabled`, `.https_probe_config.json`, `.https_probe_status.json`, callbacks, pairing artifacts, session records, logs or private `systemd`/ngrok credentials. Do not share a running device ID or the endpoint's configured personal callback URL. Only example values in documentation; keep working credentials outside the repository.

The app's current HTTP access key is suitable **only** on a trusted private LAN or private VPN, not a public port forward. The HTTPS Cloud integration contacts Lovense over TLS, but it does not make the browser dashboard an internet-safe website. The public development branch does not have a complete threat model or independent security audit.

## Preserved guarantees (software, not physical)

- Stop outranks concurrent Start, Test and pattern switch; generation and I/O locks protect against stale commands after Stop.
- Device name/connected count are verified. Any unrecognised or multiple reported devices must not be selected.
- Session transport remains pinned; errors do not silently switch to another route mid-session.
- Faults are latched and explicitly re-armed; ordinary cloud Stop confirmation is deferred, never automatically bypassed.
- HTTPS callback is historical pairing evidence, not a live motor heartbeat. The active physical state is UNKNOWN after cloud command acceptance.
- No motor command may run in a `--simulate` test.

## Hardware acceptance checklist — after code review, off-body only

- [ ] LAN-only simulator and hybrid simulator on separate port (8876), access key respected
- [ ] Real Edge 2 test: independent Motor 1/Motor 2 output and manual Stop
- [ ] Timer expiry: quiet Standby, no false connection-warning panel
- [ ] Cloud Stop: quiet completion, confirmation before next Start, with no motor output before re-arm
- [ ] Wi-Fi, Bluetooth and cloud failure during run: visible immediate fault and no unintended auto-resume
- [ ] Reconnect: Stop reconciliation; record any transient physical motion
- [ ] Pairing code/QR: only shown after authenticated explicit request, no URLs or tokens in logs
- [ ] Public LAN profile: cloud endpoint refused without any token reads
- [ ] Backup, clean install, CLI flags, updates and rollback checked on a different Linux/Pi installation
- [ ] Clarify vendor/API terms, no stable tag before approval

## Test counts

Development-machine unit tests (mocked/no physical I/O): original private v4.6 dev1 suite 94 tests, plus unified profile checks in `test_unified_profiles_v46.py`. Public LAN regression tests in `main` remain preserved and need to run against this branch in GitHub CI; don't add the two counts together until confirmed.
