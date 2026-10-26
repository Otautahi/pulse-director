# LAN-only Docker, with no cloud enable flag and no bundled credentials.
# Official Python 3.11 slim image supports amd64, arm64 and arm/v7.
FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PULSEDIRECTOR_KEY_FILE=/data/.edge_dashboard_key
WORKDIR /opt/pulsedirector
RUN groupadd --gid 10001 pulsedirector \
 && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent pulsedirector \
 && mkdir -p /data && chown 10001:10001 /data && chmod 0700 /data
COPY --chown=10001:10001 edge_dashboard.py edge2_director.py edge2_https_pairing.py edge2_pairing_ui.py ./
COPY --chown=10001:10001 https-standard-probe/https_probe.py ./https-standard-probe/https_probe.py
USER 10001:10001
EXPOSE 8765
STOPSIGNAL SIGTERM
CMD ["python3", "-B", "edge_dashboard.py", "--profile", "lan", "--bind", "0.0.0.0", "--port", "8765", "--no-print-key"]
