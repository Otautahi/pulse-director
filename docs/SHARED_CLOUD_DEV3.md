# PulseDirector v4.6 — Shared Cloud Dev3 update

**Development-only staging kit** for the existing installed v4.6 dev2 release on the Raspberry Pi. Does not download, publish or embed cloud credentials. It copies only the existing **development dashboard access key** into the new local release so your login keeps working; that key remains on your Pi with owner-only permissions. Production private v4.5.7 and the existing HTTPS callback/ngrok services are not modified, stopped, restarted or used for motor commands.

## Run after uploading and extracting the ZIP to `~/Projects/PulseDirector/uploads/`

```bash
cd ~/Projects/PulseDirector/uploads/PulseDirector-v4.6-shared-cloud-dev3
bash install-update.sh            # Stages separate dev3 release and runs all offline tests
bash check-shared.sh              # Validates existing PRIVATE pairing files read-only
```

The original dev2 release remains the active development `app/current`, and any currently running v4.6 LAN server remains unchanged. `check-shared.sh` **does not enable cloud**. It may report an older callback, which is not an installation failure.

### Optional changeover (not part of installation)

When no dev dashboard is running on port 8876, and the Edge 2 is physically off, run `bash activate-update.sh`; this changes **only** the development `app/current` symlink. The working dev2 release is retained. Then `bash run-sim.sh hybrid` to use the offline simulator. Later `bash rollback-update.sh` restores dev2 when the test server is stopped.

For future **read-only live Hybrid diagnostics**, a launcher must explicitly set both paths:

- `PULSEDIRECTOR_CLOUD_TOKEN_FILE=/home/otautahi/Projects/PulseDirector/private/.edge_cloud_token`
- `PULSEDIRECTOR_HTTPS_PROBE_DIR=/home/otautahi/Projects/PulseDirector/private/https-standard-probe`

These contain **paths only**, never the secret values. The token is read only when running the real Hybrid profile (not in simulation). Existing pairing records are validated using the same owner-only file checks. The development cloud-enable flag **is not created, copied or inferred** from production. When the shared pairing environment variable is set, the v4.6 dashboard refuses to regenerate a QR image inside production; pairing continues through the existing private helper.

The UI wording is changed to **Local API reachable** rather than equating an HTTP response with Game Mode being enabled. HTTPS pairing events are historical evidence, not heartbeat/physical Stop proof.

**Security:** Do not publish or forward the dashboard HTTP port, run concurrent live controllers, or initiate cloud motor tests from this kit. A cloud start must be explicitly enabled and validated in a separate stage. No `sudo` is used.

## Next release gates

After staging and read-only checks pass, review the seven new offline tests and manually activate the development link only after stopping the old development server. A subsequent test can launch Hybrid with read-only shared paths while the cloud enable flag remains absent. Only after separate off-body, fault-recovery and authentication checks should live cloud control be considered. GitHub draft PR #5 and `main` are untouched by this package.

PiBackup: no registration or schedule is changed. Keep versioned development backups and prepare PiBackup integration separately once v4.6 is ready for normal deployment.
