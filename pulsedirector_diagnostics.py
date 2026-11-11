"""Opt-in, read-only PulseDirector diagnostics over an owner-only Unix socket.

This module has no dependencies on Lovense APIs and never calls engine methods.
It reads cached, in-memory fields under the state lock. The normal web dashboard
does not expose this endpoint.
"""
import json
import os
from pathlib import Path
import socketserver
import stat
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

SCHEMA_VERSION = 1
APPLICATION_FAMILY = "v4.6"
TELEMETRY_FRESH_SECONDS = 45
MAX_RESPONSE_BYTES = 8192


class SnapshotUnavailable(Exception):
    """The application state could not be read within the bounded deadline."""


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _known(value, source="application_memory", freshness="current", **more):
    return {"value": value, "supported": True, "source": source,
            "freshness": freshness, **more}


def _unsupported(reason):
    return {"value": None, "supported": False, "source": "not_instrumented",
            "freshness": "unavailable", "reason": reason}


def _classify_error(message):
    """Return only pre-approved categories; never return original error text."""
    if not message:
        return None
    lowered = str(message).lower()
    if "stop not delivered" in lowered or "stop failed" in lowered:
        return "stop_delivery_failed"
    if "cloud" in lowered and ("pair" in lowered or "callback" in lowered):
        return "cloud_pairing_unavailable"
    if "cloud" in lowered and ("507" in lowered or "reject" in lowered):
        return "cloud_command_rejected"
    if "cannot reach lovense remote" in lowered or "phone wi-fi" in lowered:
        return "phone_game_mode_unreachable"
    if "multiple" in lowered or "unsupported" in lowered or "not confirmed" in lowered:
        return "device_unsupported_or_ambiguous"
    if "disconnected" in lowered or "connection lost" in lowered or "no connected toy" in lowered:
        return "device_reported_disconnected"
    return "other_unclassified_error"


def snapshot(engine, *, profile, started_monotonic, started_at_utc):
    """Build a strict allowlist from cached primitive state ONLY.

    Does not call status(), refresh_toys(), I/O helpers, cloud pairing helpers,
    motor control, or any other engine method. It never copies raw error text.
    """
    now = time.monotonic()
    if not engine.state_lock.acquire(timeout=0.05):
        raise SnapshotUnavailable("state_lock_busy")
    try:
        last_telemetry = engine.last_telemetry
        reported_connection = engine.toy_connected
        cached_error = engine.last_device_error
        current_fault = engine.fault_reason if engine.fault_latched else ""
        fault_latched = bool(engine.fault_latched)
        recovery_pending = bool(engine.stop_pending)
        cached_stop_error = bool(engine.last_stop_error)
        route = getattr(engine, "active_route", "lan")
        simulated = bool(engine.simulate)
    finally:
        engine.state_lock.release()

    route = route if route in ("lan", "cloud", "simulation", "unavailable", "unknown") else "unknown"
    if profile == "lan":
        route = "simulation" if simulated else "lan"
    if simulated:
        connection = _known("simulation", "simulated_application_state",
                            "current", current_connection_verified=False)
    elif route == "cloud":
        connection = _known("unverified", "cloud_pairing_is_not_live_telemetry",
                            "unverifiable", current_connection_verified=False)
    elif last_telemetry is None:
        connection = _unsupported("no_telemetry_observed")
    else:
        age = max(0, int(now - last_telemetry))
        state = ("reported_connected" if reported_connection is True else
                 "reported_disconnected" if reported_connection is False else "unknown")
        connection = _known(state, "cached_phone_game_mode_telemetry",
                            "fresh" if age <= TELEMETRY_FRESH_SECONDS else "stale",
                            age_seconds=age, current_connection_verified=False)

    error_category = _classify_error(cached_error)
    cached_connection_error = (
        _known(error_category, "cached_unstructured_error", "unverifiable")
        if error_category else _unsupported("no_timestamped_connection_error_history")
    )
    fault_category = _classify_error(current_fault)
    active_fault = (
        _known(fault_category, "active_fault_latch", "current")
        if fault_latched else _known(None, "active_fault_latch", "current")
    )

    return {
        "report": "PulseDirector diagnostics",
        "schema_version": SCHEMA_VERSION,
        "collected_at_utc": _utc_now(),
        "application": {
            "version_family": _known(APPLICATION_FAMILY, "running_code", "current"),
            "exact_release": _unsupported("exact_installed_release_not_exposed"),
            "profile": _known(profile, "startup_configuration", "current"),
            "started_at_utc": _known(started_at_utc, "diagnostics_server_start", "current"),
            "uptime_seconds": _known(max(0, int(now - started_monotonic)),
                                     "monotonic_process_uptime", "current"),
            "last_classified_error": _unsupported("no_timestamped_application_error_history"),
            "current_fault_category": active_fault,
        },
        "connection": {
            "last_known_state": connection,
            "transport": _known(route, "cached_application_route", "current"),
            "failure_count": _unsupported("connection_failure_counter_not_recorded"),
            "last_disconnection_at": _unsupported("disconnect_timestamp_not_recorded"),
            "last_reconnection_at": _unsupported("reconnect_timestamp_not_recorded"),
            "cached_error_category": cached_connection_error,
        },
        "session": {
            "last_outcome": _unsupported("session_outcome_history_not_recorded"),
            "last_interruption_category": _unsupported("session_interruption_history_not_recorded"),
        },
        "recovery": {
            "fault_latched": _known(fault_latched),
            "pending": _known(recovery_pending),
            "last_attempt": _unsupported("timestamped_recovery_attempt_not_recorded"),
            "last_outcome": _unsupported("recovery_outcome_history_not_recorded"),
        },
        "stop": {
            "last_request_outcome": _unsupported("timestamped_stop_outcome_not_recorded"),
            "cached_error_present": _known(cached_stop_error, "application_memory", "current"),
            "physical_motor_state": _known("unverified", "no_physical_motor_feedback",
                                           "unverifiable"),
        },
        "events": {
            "supported": False, "retention_seconds": 0, "max_items": 0,
            "items": [], "reason": "no_sanitized_event_history_in_current_engine",
        },
        "limitations": [
            "Cached phone reports are not a live physical device connection guarantee.",
            "Cloud pairing events are not connection heartbeats.",
            "A software or cloud Stop acknowledgement is not physical Stop proof.",
            "No historical counters or event timestamps are synthesized.",
        ],
    }


class DiagnosticsHandler(BaseHTTPRequestHandler):
    """Separate HTTP parser reachable only through a permission-checked socket."""
    server_version = "PulseDirectorDiagnostics/1"
    sys_version = ""

    def log_message(self, fmt, *args):
        return  # Never log request URLs or client-supplied text.

    def setup(self):
        super().setup()
        self.connection.settimeout(2.0)

    def _reply(self, code, obj):
        body = json.dumps(obj, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(body) > MAX_RESPONSE_BYTES:
            code = 503
            body = b'{"schema_version":1,"status":"unavailable","reason":"response_limit"}'
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/api/diagnostics/v1":
            self._reply(404, {"error": "not_found"})
            return
        try:
            result = snapshot(self.server.engine, profile=self.server.profile,
                              started_monotonic=self.server.started_monotonic,
                              started_at_utc=self.server.started_at_utc)
        except SnapshotUnavailable:
            self._reply(503, {"schema_version": SCHEMA_VERSION, "status": "unavailable",
                              "reason": "state_busy"})
        except Exception:
            self._reply(503, {"schema_version": SCHEMA_VERSION, "status": "unavailable",
                              "reason": "snapshot_error"})
        else:
            self._reply(200, result)

    def _method_not_allowed(self):
        self._reply(405, {"error": "read_only"})

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed
    do_HEAD = _method_not_allowed


class PrivateDiagnosticsServer(socketserver.UnixStreamServer):
    allow_reuse_address = False


def start_private_diagnostics_server(path, engine, *, profile):
    """Opt-in only. Path must be inside an existing owner-only 0700 directory."""
    sock_path = Path(path)
    if not sock_path.is_absolute() or len(os.fsencode(str(sock_path))) >= 100:
        raise RuntimeError("Diagnostics socket requires a short absolute path")
    parent_stat = sock_path.parent.lstat()
    if (not stat.S_ISDIR(parent_stat.st_mode) or
            parent_stat.st_uid != os.geteuid() or
            stat.S_IMODE(parent_stat.st_mode) != 0o700):
        raise RuntimeError("Diagnostics parent must be an owner-only directory (0700)")
    try:
        sock_path.lstat()
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError("Diagnostics socket already exists; verify it before cleanup")

    server = PrivateDiagnosticsServer(str(sock_path), DiagnosticsHandler)
    server.engine = engine
    server.profile = profile
    server.started_monotonic = time.monotonic()
    server.started_at_utc = _utc_now()
    server.socket_inode = sock_path.lstat().st_ino
    try:
        os.chmod(sock_path, 0o600)
        thread = threading.Thread(target=server.serve_forever,
                                  name="pulsedirector-diagnostics", daemon=True)
        thread.start()
        return server, thread
    except Exception:
        server.server_close()
        _unlink_our_socket(server)
        raise


def _unlink_our_socket(server):
    path = Path(server.server_address)
    try:
        current = path.lstat()
        if (stat.S_ISSOCK(current.st_mode) and
                current.st_uid == os.geteuid() and
                current.st_ino == server.socket_inode):
            path.unlink()
    except FileNotFoundError:
        pass


def stop_private_diagnostics_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    _unlink_our_socket(server)
