# Docker / Compose — experimental LAN-only installation

**New to PulseDirector?** This optional Docker setup runs the PulseDirector v4.6 web controller without installing Python on the host. The original [Python/Linux guide](INSTALL.md) remains available. **Docker support is experimental:** the container has not yet been physically tested with an Edge 2.

> **Safety:** Docker cannot guarantee physical Stop. A Bluetooth/phone/Wi-Fi/host outage can prevent Stop delivery. Keep the Edge 2 **off-body for initial testing**, its physical power button accessible and never run two controllers against one toy. The dashboard uses HTTP and must **never be port-forwarded to the internet**.

## 1. Compatible hosts and requirements

The Dockerfile uses the official `python:3.11-slim-bookworm` image, published for **amd64 (x86-64), arm64 and arm/v7 (32-bit Raspberry Pi 3B+)**. Docker Engine and its Compose plugin are required. This is intended for Linux computers and compatible Raspberry Pi OS; Docker Desktop on Windows/macOS may work but is **not verified with a real toy**. ARMv7 cross-building in CI is separate from real Pi hardware validation.

You also need **one Lovense Edge 2**, a phone running Lovense Remote with **Game Mode**, and a trusted local network where the Linux host can reach the phone. **Max 2, multiple toys and cloud control are not supported in this Docker configuration.**

## 2. Download and configure

Install Docker Engine and Docker Compose from the [official installation instructions](https://docs.docker.com/engine/install/). Clone a **new copy** — do not overwrite a running systemd installation:

```bash
git clone https://github.com/Otautahi/pulse-director.git
cd pulse-director
cp .env.example .env
```

Edit `.env`:

- **`PULSEDIRECTOR_PHONE_IP`** — required: the *phone's* local Wi-Fi IPv4 address while running Lovense Remote Game Mode.
- **`PULSEDIRECTOR_HOST_BIND_IP`** — defaults to `127.0.0.1`, accessible **only on the Docker host**. To access the dashboard from another authorised device, explicitly set this to the *Linux Docker host's trusted LAN IP* (example `192.168.1.20`), and restrict access using network/firewall settings. **Never use `0.0.0.0` or a public IP.**
- **`PULSEDIRECTOR_HOST_PORT`** — defaults to `8765`; change it if already occupied by another application.

Your phone IP and your Docker host IP are **different**. The example IP address is not your real address.

## 3. Build and start

Keep the Edge 2 **off-body** and ensure no other controller is connected to it.

```bash
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

This builds an image locally — **no prebuilt image is published** — and starts `--profile lan` with no cloud credentials. The container runs as a non-root user (UID 10001), with a read-only root filesystem and dropped Linux capabilities. A separate Docker named volume stores its private dashboard access key; your existing Pi/service files are **not altered**.

## 4. Open the dashboard and get the access key

Open `http://127.0.0.1:8765` in a browser **on the Docker host**. If you set your *host's trusted LAN IP* in `.env`, open `http://HOST_BIND_IP:8765` from an authorised home-network device instead.

Get the dashboard key **privately on the Docker host**:

```bash
docker compose exec -T pulsedirector cat /data/.edge_dashboard_key
```

Enter it at the login screen. **Never share this key** on Reddit, GitHub, in screenshots, or in public logs. The container uses `--no-print-key` so it isn't printed in normal Docker logs.

Confirm one Edge 2 is detected. Start at the **lowest intensity**, test each motor separately, and verify that manual and timed Stop **physically stop** the toy. A successful API result is not proof of physical inactivity.

## 5. Stop and preserve data

Press **STOP ALL MOTORS** in the dashboard and verify the toy's physical state before running:

```bash
docker compose down
```

This **preserves** the named volume and key. **Do not run `docker compose down -v`** unless you want to delete the persistent key. Automatic container restart is disabled in this experimental setup. Avoid forced termination, network outages and host power loss during a session; even graceful shutdown does not guarantee Stop over a failed connection.

## 6. Optional preview with no toy

After `docker compose build`, run a separate simulator (not the live Compose service):

```bash
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=1m,mode=1777 \
  -e PULSEDIRECTOR_KEY_FILE=/tmp/.edge_dashboard_key \
  -p 127.0.0.1:8876:8765 pulsedirector:local \
  python3 -B edge_dashboard.py --profile lan --simulate --bind 0.0.0.0 --port 8765
```

Open `http://127.0.0.1:8876` **on the Docker host**. This simulator performs **no real toy or cloud control**, and uses a temporary key separate from your live Compose volume. Press Ctrl+C to exit.

## Troubleshooting and limits

- **Compose complains about phone IP:** edit `.env`; `PULSEDIRECTOR_PHONE_IP` is required.
- **Browser won't open from your phone:** `127.0.0.1` means Docker-host-only. Choose the **host's trusted LAN IP** explicitly (not `0.0.0.0` or the phone's IP).
- **Edge 2 isn't detected:** check Bluetooth, Lovense Remote/Game Mode, correct phone IP, and Wi-Fi guest isolation; Docker bridge/NAT and your network may affect reachability.
- **Key missing/permissions:** this image runs as UID/GID 10001 and persists keys in a named volume with permission `0600`. Don't loosen permissions or run the service as root.
- **Already running a private Pi installation:** Docker uses its **own key, container and volume**. It does not change your systemd service, PiBackup configuration or old rollback. Do not have two live controllers command the same Edge 2.
- **Hybrid support:** this is **LAN-only Docker**. See [HYBRID.md](HYBRID.md) for separate, experimental requirements; no turn-key cloud container is provided.

Read [security limits](SECURITY.md) before operating a physical device. These software restrictions are **not** an emergency-stop guarantee or independent safety certification.
