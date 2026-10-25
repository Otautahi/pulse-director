# Dev4 review and safety notes

1. Production v4.5.7 and other services must remain untouched.
2. `HTTPS_ENABLE_FLAG` is **not** copied from Dev3. Its removal must invalidate readiness, block new Vibrate commands, and latch active sessions. A flag recreated after revocation cannot re-arm the same process.
3. STOP and recovery STOP must remain permitted on the pinned cloud route while cloud activation is disabled. A cloud API success does **not** prove motor inactivity.
4. Tests that previously forced `https_cloud_enabled=True` now use a temporary owner-only flag; no gating bypass is inserted into production source.
5. `app/current` is not changed by installation. Activation/rollback each require port 8876 unoccupied.
6. No QR generation, production restart, systemd changes, key export, new cloud identities or public repository writes.
7. Off-body hardware testing is not required for this staging update. A separate explicit approval is required before any cloud motor tests.
