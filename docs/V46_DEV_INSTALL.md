# PulseDirector v4.6 — isolated Raspberry Pi development candidate

**Status:** Experimental. No deployment to production. Simulation only, pinned to reviewed commit `e96b4129b56a4d94520ca040081ee206614f2278` (21 October 2026).

This kit is an **online bootstrap installer**, not a full offline source snapshot. It clones the existing public `develop/v4.6-hybrid` branch, verifies the exact SHA, applies three limited local portability fixes, runs offline tests, and promotes it within a development-only versioned directory.

It does **not** merge GitHub branches, push commits, install production services, enable cloud, touch Pi-hole/WireGuard or communicate with physical devices. Any proposed source changes need independent GitHub review before a later commit to the existing v4.6 branch.

## Requirements

- Your normal unprivileged Raspberry Pi account (e.g. `otautahi`), **never sudo**.
- Working Pi internet connectivity to GitHub for cloning; Git, Bash and Python 3.10+ with the `venv` module.
- Package transferred via WinSCP (Windows) or Rasp Pi Controller (Android).
- At least ~100 MB available for the Python environment and cloned source (allow more for git history/backups).
- No other process listening on Pi loopback port 8876.

If Python's venv is missing, stop. On Raspberry Pi OS, an administrator can separately install the OS package `python3-venv` after reviewing impact; the development installer does not change OS packages.

## 1. Transfer and unpack

In WinSCP, copy `PulseDirector-v4.6-dev-kit.zip` into:

`/home/otautahi/Projects/PulseDirector/uploads/`

In PuTTY, login as `otautahi`, then:

```bash
cd ~/Projects/PulseDirector/uploads
unzip PulseDirector-v4.6-dev-kit.zip
cd PulseDirector-v4.6-dev-kit
bash preflight.sh
```

Read the output. This is a read-only systems check except for a temporary local port bind used to determine availability.

## 2. Install after reviewing the checks

```bash
bash install-dev.sh
```

The installer aborts if the branch HEAD differs from the pinned SHA, code isn't the reviewed `stage.sh`/pairing revision, tests fail, an existing release directory would be overwritten, or the development tree uses unsafe symlinks. It does not update any running systemd service.

Expected development layout:

```text
~/Projects/PulseDirector/
  private/                      # EXISTING PRODUCTION: untouched
  uploads/PulseDirector-v4.6-dev-kit/
  development/v4.6-unified/
    .venv/                      # isolated local Python interpreter
    app/releases/e96b4129b56a/ # candidate source + three portability patches
    app/current -> releases/e96b4129b56a
    config/ data/ logs/ backups/ updates/ uploads/
```

The patched source is intentionally **locally modified** (`git status` not clean); nothing is pushed to GitHub. Do not run `git pull` against this checkout or assume local fixes have been merged into the development branch.

## 3. Run an isolated simulator in PuTTY

LAN-only:

```bash
cd ~/Projects/PulseDirector/uploads/PulseDirector-v4.6-dev-kit
bash run-sim.sh lan
```

Hybrid UI (still simulated; does not load cloud credentials):

```bash
bash run-sim.sh hybrid
```

Only one at a time. Both always pass `--simulate --bind 127.0.0.1 --port 8876 --no-print-key`. No real-device I/O occurs. Press **Ctrl+C** to exit. The program generates an independent development access key under `development/.../app/current/.edge_dashboard_key` with private permissions. To view the key within your private PuTTY session (not in screenshots or shared logs):

```bash
cat ~/Projects/PulseDirector/development/v4.6-unified/app/current/.edge_dashboard_key
```

### Access from your Windows PC over an SSH tunnel

In PuTTY before opening your connection:

1. Go to **Connection > SSH > Tunnels**.
2. Enter **Source port:** `8876`; **Destination:** `127.0.0.1:8876`.
3. Click **Add**, then connect or reconnect to your Pi.
4. With the simulator running in a separate PuTTY session, open `http://127.0.0.1:8876` on your PC.

Do not forward 8876 on the router. Do not use the production 8765 port for this test.

## 4. Verify functionality

Check both profiles, authentication, mode selection, manual and autonomous simulations, Stop All, session expiry, Quiet Stop, fault indication and that cloud pairing is refused in LAN mode. This is a UI/software simulation, not a physical Stop validation. Keep the working production application untouched.

The installer runs the existing development test suite plus 4 new local portability tests. The official branch already passed GitHub's four-version Python matrix; these local patches have **not** been tested by that remote CI and must be committed/retested before public release.

## 5. Development-only rollback

Stop the simulator first (Ctrl+C), then run:

```bash
bash rollback-dev.sh
```

This restores the previous `app/current` development symlink. On a first-ever install with no previous release, it removes only that development symlink and retains source files. It never restores or modifies the private production application. A timestamped pointer backup is kept under `development/v4.6-unified/backups/`.

## Release blockers

- Independent history/release-assets/secrets audit, including any old commits (not complete).
- Portable pairing helper path must be committed to the unified branch and re-tested.
- Existing v4.5 `docs/INSTALL.md` needs updating or an explicit version split.
- Correct `stage.sh` must be committed/tested in GitHub CI.
- Need CI-based secret scanning; `.gitignore` alone does not protect Git history.
- No v4.6 systemd service installation, cloud callback endpoint provisioning or API/vendor terms approval is included in this simulation-only kit.
- Real hardware requires a separate **off-body test plan**, a physical disconnect option, and explicit owner approval. Bluetooth reconnect can briefly reactivate the device before software Stop succeeds.

## Optional dedicated user service template — deliberately NOT installed

`services/pulsedirector-v46-sim.service` is a separate **user-level** systemd unit template reserved for a later, explicitly approved, simulator-only deployment. It always includes `--simulate` and binds to localhost port 8876. This kit does not copy the unit to `~/.config/systemd/user`, does not run `systemctl`, and does not enable or start any service. Use the interactive foreground scripts for initial verification.
