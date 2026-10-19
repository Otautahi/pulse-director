#!/usr/bin/env python3
"""PulseDirector v4.6 unified development candidate: LAN-only and optional hybrid profiles.

Home LAN uses Lovense Remote Game Mode. Remote cloud uses the *separate,
authenticated* HTTPS callback UID. The old Socket.IO Cloud Keeper is disabled.
Cloud is OFF until the owner approves off-body pilot testing. Cached callback
reports and HTTP 200 are NOT live Bluetooth/physical Stop confirmation.
Access via existing WireGuard VPN only; do not expose the dashboard port.
"""
import argparse
import hmac
from edge2_pairing_ui import PairingQRManager
import json
import math
import os
from pathlib import Path
import random
from edge2_director import AutonomousDirector, STYLES, FLOWS
import subprocess
import secrets
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from datetime import datetime, timezone
from edge2_https_pairing import verified_pairing, PairingError

MODES = {"autonomous", "wave", "pulse", "alternate", "chase", "sync", "ramp", "random",
         "anchor", "heartbeat", "orbit", "cascade", "flutter", "tide",
         "motor1", "motor2", "manual", "test", "echo", "drift", "steps", "ripple"}
RANDOM_MODES = ("wave", "pulse", "alternate", "chase", "sync", "ramp",
                "anchor", "heartbeat", "orbit", "cascade", "flutter", "tide", "echo", "drift", "steps", "ripple")
DEFAULT_PHONE = "127.0.0.1"  # Users must provide their own Lovense Remote Game Mode IP
CLOUD_ENDPOINT = "https://api.lovense-api.com/api/lan/v2/command"
CLOUD_TOKEN_FILE = Path(__file__).resolve().parent / ".edge_cloud_token"
KEY_FILE = Path(__file__).resolve().parent / ".edge_dashboard_key"
KEEPER_FILE = Path(__file__).resolve().parent / ".edge_cloud_keeper_status.json"
KEEPER_STALE_SECONDS = 25
HTTPS_ENABLE_FLAG = Path(__file__).resolve().parent / ".edge_https_cloud_enabled"
# Conservative *policy* limits, NOT a reliable connectivity watchdog.
# HTTPS callbacks are events, not heartbeats. A 200 can be returned offline.
CLOUD_CALLBACK_MAX_AGE_SECONDS = 90
CLOUD_MAX_SESSION_SECONDS = 7200  # Timed cloud sessions: up to 120 minutes; still callback-gated.



def limited_number(value, low, high, integral=False):
    try:
        val = float(value)
        if not math.isfinite(val):
            raise ValueError("Not a finite number")
        val = min(high, max(low, val))
        return int(round(val)) if integral else val
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"Expected a number between {low} and {high}") from None


class Engine:
    def __init__(self, phone, simulate=False):
        self.url = f"http://{phone}:20010/command"
        self.simulate = simulate
        self.state_lock = threading.Lock()
        self.io_lock = threading.Lock()
        self.wake = threading.Event()
        self.close = threading.Event()
        self.mode = "idle"
        self.generation = 0
        # An explicit Stop invalidates a Start/Test still selecting a route.
        self.stop_epoch = 0
        self.stop_in_flight = 0
        self.fault_latched = False
        self.fault_reason = ""
        self.fault_route = None
        # True only for an ordinary HTTPS cloud Stop accepted by the server.
        # Separate routine acknowledgement from real communication faults.
        self.routine_cloud_stop_confirm_required = False
        self.stop_pending = False
        self.stop_acks = 0
        self.stop_attempts = 0
        self.last_stop_error = ""
        self.fault_serial = 0
        self.recovery_wake = threading.Event()
        self.started = 0.0
        self.end = 0.0
        self.max_level = 10
        self.speed = 3
        self.minutes = 5.0
        self.until_stopped = False
        self.motor1 = 4
        self.motor2 = 4
        self.motor2_support = 65  # Pattern Motor 2 strength as % of its programmed peak
        self.display1 = 0
        self.display2 = 0
        self.message = "Ready — connect your Edge 2 in Lovense Remote."
        self.random_modes = []
        self.director = None
        self.director_style = "confident"
        self.director_surprise = 4
        self.director_flow = "driving"
        # Reported by Lovense Remote, not measured directly by this program.
        self.battery = None
        self.toy_connected = None
        self.device_name = "Edge 2"
        self.last_telemetry = None
        self.last_device_error = ""
        self.session_commands = 0
        self.total_commands = 0
        self.worker = threading.Thread(target=self._loop, name="edge-pattern-worker", daemon=True)
        self.telemetry_worker = threading.Thread(target=self._telemetry_loop, name="edge-telemetry", daemon=True)
        self.recovery_worker = threading.Thread(target=self._recovery_loop, name="edge-stop-recovery", daemon=True)
        self.worker.start()
        self.telemetry_worker.start()
        self.recovery_worker.start()

    def _api(self, payload):
        if self.simulate:
            return {"code": 200, "type": "ok", "simulated": True}
        req = Request(self.url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json", "X-platform": "Pi-Edge-Dashboard"},
                      method="POST")
        try:
            with urlopen(req, timeout=2.5) as response:
                result = json.load(response)
        except (URLError, HTTPError, OSError, TimeoutError) as exc:
            raise RuntimeError(f"Cannot reach Lovense Remote ({exc}). Check Game Mode and phone Wi-Fi.") from exc
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError("Lovense Remote returned an unexpected response") from exc
        if not isinstance(result, dict):
            raise RuntimeError("Lovense Remote returned an unexpected response")
        if result.get("code") != 200:
            raise RuntimeError(f"Lovense returned: {result}")
        return result

    def _send_levels(self, gen, a, b):
        # Serialise with STOP, and recheck after waiting on I/O lock so a
        # previous generation cannot switch the toy back on after STOP.
        with self.io_lock:
            with self.state_lock:
                if gen != self.generation or self.mode == "idle" or self.fault_latched:
                    return False
                if time.monotonic() >= self.end:
                    return False
            self._api({"command": "Function", "action": f"Vibrate1:{a},Vibrate2:{b}",
                       "timeSec": 2, "stopPrevious": 1, "apiVer": 1})
            with self.state_lock:
                if gen == self.generation:
                    self.display1 = a
                    self.display2 = b
                    self.session_commands += 1
                    self.total_commands += 1
        return True

    def _send_stop(self):
        with self.io_lock:
            # HTTPS pilot has now confirmed API acceptance for stopPrevious=1
            # on cloud Stop (NOT physical delivery); LAN uses it too.
            return self._api({"command": "Function", "action": "Stop", "timeSec": 0,
                              "stopPrevious": 1, "apiVer": 1})

    def _set_idle(self, why, cancel_pending=True, fault=False):
        with self.state_lock:
            self.generation += 1
            if cancel_pending:
                self.stop_epoch += 1
            self.mode = "idle"
            self.end = 0.0
            self.display1 = self.display2 = 0
            self.message = why
            if fault:
                # A connection or motor-control failure is never a routine Stop.
                self.routine_cloud_stop_confirm_required = False
            if fault and not self.fault_latched:
                self.fault_serial += 1
                self.fault_latched = True
                self.fault_reason = why
                # A recovering session MUST use the original route only.
                requested = getattr(self, 'active_route', 'lan')
                self.fault_route = requested if requested in ('lan', 'cloud', 'simulation') else 'lan' 
                self.stop_pending = True
                self.stop_acks = 0
            self.wake.set()

    def stop(self, why="Stopped", fault=False, cancel_pending=True):
        """Stop using the original transport; API success is not physical proof.

        During Stop, prevent idle telemetry from selecting a different route.
        Multiple simultaneous Stop calls are permitted; all increment a pin
        counter until their own request has completed.
        """
        with self.state_lock:
            self.stop_in_flight += 1
            old_route = getattr(self, 'active_route', 'lan')
            original_route = old_route if old_route in ('lan', 'cloud', 'simulation') else 'lan'
        try:
            self._set_idle(why, cancel_pending=cancel_pending, fault=fault)
            try:
                self._send_stop()
            except RuntimeError as exc:
                with self.state_lock:
                    self.routine_cloud_stop_confirm_required = False
                    if not self.fault_latched:
                        self.fault_serial += 1
                        self.fault_latched = True
                        self.fault_reason = why
                        self.fault_route = original_route
                    self.stop_pending = True
                    self.stop_acks = 0
                    self.last_stop_error = str(exc)
                    self.message = ("STOP NOT DELIVERED; physical motor state UNKNOWN. "
                                    "Check physical device. " + str(exc))
                self.recovery_wake.set()
                raise
            with self.state_lock:
                if self.fault_latched:
                    self.stop_pending = True
                    self.last_stop_error = ""
                    self.stop_acks = min(self.stop_acks + 1, 2)
                    self.message = ("Fault detected; verifying Stop on original route. "
                                    "Physical motor state unknown.")
                    self.recovery_wake.set()
            return self.status()
        finally:
            with self.state_lock:
                self.stop_in_flight -= 1

    def acknowledge_fault(self):
        with self.state_lock:
            if self.mode != "idle" or self.stop_pending or self.stop_in_flight:
                raise RuntimeError("Stop recovery incomplete; check physical device")
            if self.fault_latched:
                self.fault_latched = False
                self.fault_reason = ""
                self.fault_route = None
                self.routine_cloud_stop_confirm_required = False
                self.last_stop_error = ""
                self.message = "Fault acknowledged; physical state was not independently measured."
        return self.status()

    def _recovery_ready(self, route):
        # Only one verified Edge 2 can satisfy recovery. This base implementation
        # is LAN-only; HybridEngine supplies explicit separate cloud readiness.
        return self.refresh_toys()["toyConnected"] is True

    def _recovery_loop(self):
        # Do not replay a motor command, ever. Only Stop on the pinned route.
        while not self.close.is_set():
            with self.state_lock:
                pending = self.stop_pending
                route = self.fault_route
                serial = self.fault_serial
            if pending:
                # Three HTTPS server ACKs provide no device-level assurance.
                # Stop retrying after three accepted cloud attempts, but KEEP
                # the lock until an explicit physical power-off confirmation.
                with self.state_lock:
                    exhausted_cloud = route == "cloud" and self.stop_acks >= 3
                if exhausted_cloud:
                    self.recovery_wake.wait(1.0)
                    self.recovery_wake.clear()
                    continue
                try:
                    ready = self._recovery_ready(route)
                    if ready:
                        with self.state_lock:
                            still_pending = self.stop_pending and self.fault_serial == serial
                        if still_pending:
                            self._send_stop()
                            with self.state_lock:
                                if self.stop_pending and self.fault_serial == serial:
                                    self.stop_acks += 1
                                    self.stop_attempts += 1
                                    self.last_stop_error = ""
                                    if self.stop_acks >= 3:
                                        if route == "cloud":
                                            self.stop_pending = True
                                            self.message = ("Cloud server accepted three recovery Stops; "
                                                            "PHYSICAL STOP UNKNOWN. Power off device to reset lock.")
                                        else:
                                            self.stop_pending = False
                                            self.message = ("Recovery Stop accepted by phone API on original route; "
                                                            "physical state NOT verified. Check toy and acknowledge.")
                                    else:
                                        self.message = "Recovery Stop sent; checking again on original route."
                except RuntimeError as exc:
                    with self.state_lock:
                        if self.stop_pending and self.fault_serial == serial:
                            self.stop_acks = 0
                            self.last_stop_error = str(exc)
                            self.message = ("STOP NOT DELIVERED; device state UNKNOWN. " + str(exc))
            self.recovery_wake.wait(1.0)
            self.recovery_wake.clear()

    def start(self, body, expected_stop_epoch=None, route=None):
        if not isinstance(body, dict):
            raise ValueError("Invalid settings")
        mode = body.get("mode", "wave")
        if mode not in MODES or mode == "test":
            raise ValueError("Unknown pattern mode")
        max_level = limited_number(body.get("max", 10), 1, 20, True)
        speed = limited_number(body.get("speed", 3), 1, 5, True)
        minutes = limited_number(body.get("minutes", 5), .25, 120)
        unlimited = body.get("untilStopped", False)
        if type(unlimited) is not bool:
            raise ValueError("Invalid unlimited timer flag")
        m1 = limited_number(body.get("motor1", 4), 0, 20, True)
        m2 = limited_number(body.get("motor2", 4), 0, 20, True)
        support = limited_number(body.get("support", 65), 0, 100, True)
        style = body.get("style", "confident")
        if not isinstance(style, str) or style not in STYLES:
            raise ValueError("Invalid Director style")
        flow = body.get("flow", "driving")
        if not isinstance(flow, str) or flow not in FLOWS:
            raise ValueError("Invalid Director session flow")
        surprise = limited_number(body.get("surprise", 4), 0, 6, True)
        if not 1 <= surprise <= 5:
            raise ValueError("Surprise must be between 1 and 5")
        with self.state_lock:
            if self.fault_latched or self.close.is_set() or self.stop_in_flight:
                raise RuntimeError("Connection fault locked or Stop pending: cannot Start")
            if expected_stop_epoch is not None and self.stop_epoch != expected_stop_epoch:
                raise RuntimeError("Start cancelled by STOP")
            if route is not None:
                self.active_route = route
            self.generation += 1
            self.mode = mode
            self.max_level = max_level
            self.speed = speed
            self.minutes = minutes
            self.until_stopped = unlimited
            self.motor1 = min(m1, max_level)
            self.motor2 = min(m2, max_level)
            self.motor2_support = support
            self.director_style = style
            self.director_surprise = surprise
            self.director_flow = flow
            self.director = AutonomousDirector(style=style, surprise=surprise, flow=flow) if mode == "autonomous" else None
            self.started = time.monotonic()
            self.pattern_started = self.started
            self.end = float("inf") if unlimited else self.started + minutes * 60
            self.display1 = self.display2 = 0
            choices = []
            for _ in range(300):
                options = [item for item in RANDOM_MODES if item not in choices[-3:]]
                choices.append(random.choice(options))
            self.random_modes = choices
            self.session_commands = 0
            self.message = ("Autonomous Director · " + style.title() if mode == "autonomous"
                            else "Running: " + mode.title())
            self.wake.set()
        return self.status()

    def switch_pattern(self, body):
        """Change pattern within the existing session; retain route and deadline.

        Unlike Start, this MUST NOT issue Stop or start a new cloud session.
        A concurrent Stop or fault cancels it through the generation guard.
        """
        if not isinstance(body, dict):
            raise ValueError("Invalid settings")
        mode = body.get("mode", "wave")
        if mode not in MODES or mode == "test":
            raise ValueError("Unknown pattern mode")
        cap = limited_number(body.get("max", 10), 1, 20, True)
        speed = limited_number(body.get("speed", 3), 1, 5, True)
        m1 = limited_number(body.get("motor1", 4), 0, 20, True)
        m2 = limited_number(body.get("motor2", 4), 0, 20, True)
        support = limited_number(body.get("support", 65), 0, 100, True)
        style = body.get("style", "confident")
        flow = body.get("flow", "driving")
        surprise = limited_number(body.get("surprise", 4), 1, 5, True)
        if style not in STYLES or flow not in FLOWS:
            raise ValueError("Invalid Director settings")
        with self.state_lock:
            if (self.mode == "idle" or self.fault_latched or self.stop_pending or
                    self.stop_in_flight or self.close.is_set() or
                    time.monotonic() >= self.end):
                raise RuntimeError("No safe active session to switch; use Start")
            self.generation += 1
            self.mode = mode
            self.max_level = cap
            self.speed = speed
            self.motor1 = min(m1, cap)
            self.motor2 = min(m2, cap)
            self.motor2_support = support
            self.director_style = style
            self.director_flow = flow
            self.director_surprise = surprise
            # Reset the pattern clock only; preserve overall session clock.
            self.pattern_started = time.monotonic()
            self.director = AutonomousDirector(style=style, surprise=surprise, flow=flow) if mode == "autonomous" else None
            if mode == "random":
                self.random_modes = [random.choice(RANDOM_MODES) for _ in range(300)]
            self.message = "Switched to " + ("Autonomous Director" if mode == "autonomous" else mode.title()) + "; session continues"
            self.wake.set()
        return self.status()

    def test(self, expected_stop_epoch=None, route=None):
        # Tests separate motor commands; a device without support will error.
        with self.state_lock:
            if self.fault_latched or self.close.is_set() or self.stop_in_flight:
                raise RuntimeError("Connection fault locked or Stop pending: cannot Test")
            if expected_stop_epoch is not None and self.stop_epoch != expected_stop_epoch:
                raise RuntimeError("Motor test cancelled by STOP")
            if route is not None:
                self.active_route = route
            self.generation += 1
            self.mode = "test"
            self.until_stopped = False
            self.max_level = 5
            self.speed = 3
            self.started = time.monotonic()
            self.pattern_started = self.started
            self.end = self.started + 7.0
            self.display1 = self.display2 = 0
            self.session_commands = 0
            self.message = "Testing motor 1, motor 2, then both (about 7 seconds)"
            self.wake.set()
        return self.status()

    @staticmethod
    def _extract_toy(data):
        """GetToys often wraps `data.toys` as a JSON-encoded string."""
        info = data.get("data", {})
        if isinstance(info, str):
            try:
                info = json.loads(info)
            except (ValueError, TypeError):
                return None
        if isinstance(info, dict):
            info = info.get("toys", info)
        if isinstance(info, str):
            try:
                info = json.loads(info)
            except (ValueError, TypeError):
                return None
        if isinstance(info, dict):
            if "battery" in info or "status" in info or "name" in info:
                devices = [info]
            else:
                devices = list(info.values())
        elif isinstance(info, list):
            devices = info
        else:
            devices = []
        devices = [item for item in devices if isinstance(item, dict)]
        connected = [x for x in devices if str(x.get("status", "")).lower() in ("1", "true", "connected")]
        if len(connected) != 1:
            return None
        toy = connected[0]
        model = str(toy.get("name") or toy.get("model") or "").lower().strip()
        if "".join(ch for ch in model if ch.isalnum()) not in ("edge", "edge2"):
            return None
        return toy

    def refresh_toys(self):
        if self.simulate:
            data = {"code": 200, "data": {"toys": json.dumps({"simulated": {"name": "edge", "battery": 72, "status": "1"}})}}
        else:
            with self.io_lock:
                data = self._api({"command": "GetToys"})
        toy = self._extract_toy(data)
        with self.state_lock:
            self.last_telemetry = time.monotonic()
            if toy is None:
                self.toy_connected = False
                self.last_device_error = "No connected toy reported"
            else:
                self.toy_connected = str(toy.get("status", "1")).lower() in ("1", "true", "connected")
                raw_battery = toy.get("battery")
                try:
                    pct = int(raw_battery)
                    if 0 <= pct <= 100:
                        self.battery = pct
                except (ValueError, TypeError):
                    pass
                name = str(toy.get("nickName") or toy.get("name") or "Edge 2").strip()
                self.device_name = "Edge 2" if name.lower() == "edge" else name[:40]
                self.last_device_error = "" if self.toy_connected else "Lovense reports disconnected"
        return self.status()

    def _telemetry_loop(self):
        if self.close.wait(.5):
            return
        while not self.close.is_set():
            try:
                status = self.refresh_toys()
            except RuntimeError as exc:
                with self.state_lock:
                    self.toy_connected = False
                    self.last_telemetry = time.monotonic()
                    self.last_device_error = str(exc)
                    status = {"toyConnected": False, "running": self.mode != "idle"}
            if status["toyConnected"] is False and status["running"] and not self.close.is_set():
                with self.state_lock:
                    still_running = self.mode != "idle"
                if still_running:
                    try:
                        self.stop("Connection lost; physical state unknown", fault=True)
                    except RuntimeError:
                        pass
            with self.state_lock:
                active = self.mode != "idle" or self.stop_pending
            self.close.wait(2.0 if active else 20.0)

    def status(self):
        with self.state_lock:
            now = time.monotonic()
            left = max(0, self.end - now) if self.mode != "idle" and not self.until_stopped else 0
            elapsed = max(0, now - self.started) if self.mode != "idle" else 0
            freshness = int(now - self.last_telemetry) if self.last_telemetry is not None else None
            director_state = (self.director.snapshot(elapsed) if self.mode == "autonomous" and self.director else None)
            decisions = director_state["decisions"] if director_state else 0
            return {"mode": self.mode, "motor1": self.display1, "motor2": self.display2,
                    "directorStyle": self.director_style, "directorSurprise": self.director_surprise,
                    "directorDecisions": decisions, "directorFlow": self.director_flow,
                    "directorScene": director_state["scene"] if director_state else None,
                    "directorPhase": director_state["phase"] if director_state else None,
                    "directorEnergy": director_state["energy"] if director_state else 0,
                    "directorIntent": director_state["intent"] if director_state else "",
                    "directorReprises": director_state["reprises"] if director_state else 0,
                    "directorSceneSecondsLeft": director_state["sceneSecondsLeft"] if director_state else 0,
                    "sessionProgress": min(100, max(0, round(100 * elapsed / max(1, self.minutes * 60)))) if self.mode != "idle" and not self.until_stopped else 0,
                    "secondsLeft": None if self.mode != "idle" and self.until_stopped else int(math.ceil(left)),
                    "untilStopped": self.mode != "idle" and self.until_stopped,
                    "elapsedSeconds": int(elapsed),
                    "running": self.mode != "idle", "profile": "lan", "connectionMode": "simulation" if self.simulate else "lan", "max": self.max_level,
                    "speed": self.speed, "support": self.motor2_support, "message": self.message,
                    "simulated": self.simulate, "battery": self.battery,
                    "toyConnected": self.toy_connected, "deviceName": self.device_name,
                    "lastDeviceCheckSec": freshness, "lastDeviceError": self.last_device_error,
                    "sessionCommands": self.session_commands,
                    "totalCommands": self.total_commands,
                    "faultLatched": self.fault_latched,
                    "faultReason": self.fault_reason,
                    "faultRoute": self.fault_route,
                    "stopPending": self.stop_pending,
                    "stopAcks": self.stop_acks,
                    "stopAttempts": self.stop_attempts,
                    "lastStopError": self.last_stop_error,
                    "physicalStopVerified": False}

    def _pattern(self, mode, elapsed, maximum, speed, m1, m2, rnd, support=65):
        """Motor 1-led waveforms with independent, complementary Motor 2 accents.

        Timing is intentionally measured in seconds, not sub-second clicks:
        the HTTPS cloud backend samples approximately every 1.2-1.7 seconds.
        Motor 2 strength is user adjustable for preset modes; test, manual,
        and solo-motor modes remain unmodified.
        """
        factor = (speed + 1) / 4.0   # 0.5x at slowest, 1x default, 1.5x fastest
        t = max(0., elapsed * factor)
        if mode == "random":
            index = int(t / 18.)
            mode = rnd[index % len(rnd)] if rnd else "wave"
            t %= 18.
        if mode == "test":
            if elapsed < 2.2:
                return 4, 0
            if elapsed < 4.4:
                return 0, 4
            return 4, 4
        if mode == "manual":
            return min(maximum, m1), min(maximum, m2)
        if mode == "motor1":
            return maximum, 0
        if mode == "motor2":
            return 0, maximum

        # Smooth periodic swell: starts at a low point and rises to a peak.
        def swell(time_value, period):
            return (1.0 - math.cos(2.0 * math.pi * time_value / period)) / 2.0

        def triangle(time_value, period):
            position = (time_value % period) / period
            return 1.0 - abs(2.0 * position - 1.0)

        def pair(a, b):
            a = max(0., min(1., a))
            b = max(0., min(1., b))
            contribution = max(0., min(1., support / 100.))
            return round(maximum * a), round(maximum * b * contribution)

        if mode == "wave":
            # Motor 1 rises first; Motor 2 follows 2.6 phase-seconds later.
            return pair(.18 + .82 * swell(t, 10.), .88 * swell(t - 2.6, 10.))
        if mode == "sync":
            # Simultaneous timing with an adjustable Motor 2 level.
            w = swell(t, 9.)
            return pair(.18 + .82 * w, .18 + .82 * w)
        if mode == "pulse":
            # Overlapping bursts with a long enough phase for cloud commands.
            p = t % 8.5
            return pair(.87 if p < 4.0 else .08, .82 if 2.1 <= p < 5.5 else 0)
        if mode == "alternate":
            # Motor 1 leads for most of the cycle, then Motor 2 replies.
            p = t % 14.
            return pair(.91 if p < 7.3 else (.12 if p < 9.4 else 0),
                        .86 if 7.3 <= p < 12.3 else 0)
        if mode == "chase":
            # Motor 1 -> both -> Motor 2 -> rest.
            p = t % 15.
            if p < 4.4:
                return pair(.85, 0)
            if p < 9.0:
                return pair(.87, .85)
            if p < 12.6:
                return pair(0, .82)
            return pair(0, 0)
        if mode == "ramp":
            # Gradual rise/fall with an offset secondary rise.
            return pair(.12 + .88 * triangle(t, 14.),
                        .88 * triangle(t - 2.7, 14.))
        if mode == "anchor":
            # Continuous primary output; spaced accents from Motor 2.
            p = t % 10.
            return pair(.60 + .23 * swell(t, 10.), .95 if 4.0 <= p < 7.5 else .05)
        if mode == "heartbeat":
            # Distinct primary double pulse and delayed secondary beat.
            p = t % 17.2
            a = .87 if (1.0 <= p < 4.6 or 6.2 <= p < 9.8) else .09
            b = .95 if 10.1 <= p < 14.0 else 0
            return pair(a, b)
        if mode == "orbit":
            # Independent wave periods prevent repetitive perfect overlap.
            return pair(.30 + .70 * swell(t, 10.5),
                        .13 + .87 * swell(t + 2.7, 14.))
        if mode == "cascade":
            # Secondary wave follows primary by about three seconds.
            return pair(.20 + .80 * swell(t, 12.), .93 * swell(t - 3.0, 12.))
        if mode == "flutter":
            # Slow primary bed with clearly spaced secondary accents.
            p = t % 7.5
            return pair(.51 + .29 * swell(t, 12.), .92 if 2.0 <= p < 5.6 else 0)
        if mode == "tide":
            # Deep slow crescendos that crest at different times.
            return pair(.15 + .85 * swell(t, 16.), .90 * swell(t - 4., 16.))
        if mode == "echo":
            # Two distinct short responses rather than a symmetric overlap.
            p = t % 12.
            return pair(.84 if 0.8 <= p < 4.8 else (.34 if 5.0 <= p < 7.4 else .08),
                        .88 if 5.0 <= p < 9.4 else 0)
        if mode == "drift":
            # Slow, slightly asynchronous waves; avoids hard edges.
            return pair(.27 + .56 * swell(t, 18.), .18 + .74 * swell(t+3.9, 23.))
        if mode == "steps":
            # Smooth stepped plateaus, secondary climbing out of phase.
            p = t % 16.
            a = .26 if p < 4 else .48 if p < 8 else .77 if p < 12 else .35
            b = .12 if p < 4 else .33 if p < 8 else .55 if p < 12 else .87
            return pair(a, b)
        if mode == "ripple":
            # Nested slow waves with a drifting offset on the second motor.
            a = .24 + .53 * swell(t, 10.5) + .18 * swell(t, 3.7)
            b = .12 + .58 * swell(t+2.5, 12.7) + .22 * swell(t, 5.1)
            return pair(a, b)
        return 0, 0

    def _loop(self):
        while not self.close.is_set():
            with self.state_lock:
                mode = self.mode
                gen = self.generation
                end = self.end
                start = self.started
                cap = self.max_level
                speed = self.speed
                m1, m2 = self.motor1, self.motor2
                support = self.motor2_support
                rnd = self.random_modes
                director = self.director
                pattern_start = getattr(self, "pattern_started", start)
                pattern_elapsed = max(0.0, time.monotonic() - pattern_start)
                # Unlimited Director gets a moving virtual horizon, never a
                # backwards-reset scene clock or permanent end-of-session fade.
                session_seconds = max(1800, pattern_elapsed * 2 + 900) if self.until_stopped else self.minutes * 60
            if mode == "idle":
                self.wake.wait(1)
                self.wake.clear()
                continue
            now = time.monotonic()
            if now >= end:
                # Only end the generation that actually expired.
                with self.state_lock:
                    still_current = gen == self.generation
                if still_current:
                    try:
                        self.stop("Session ended — automatic stop sent")
                    except RuntimeError:
                        pass
                continue
            if mode == "autonomous" and director is not None:
                a, b = director.levels(now - pattern_start, cap, speed, support, session_seconds)
            else:
                a, b = self._pattern(mode, now - pattern_start, cap, speed, m1, m2, rnd, support)
            try:
                self._send_levels(gen, a, b)
            except RuntimeError as exc:
                with self.state_lock:
                    still_current = gen == self.generation
                if still_current:
                    try:
                        self.stop(f"Connection error: {exc}", fault=True)
                    except RuntimeError:
                        pass
            # 0.9 s at speed 1 and 0.4 s at speed 5.
            interval = max(1.15, 1.8 - .12 * speed) if getattr(self, 'active_route', 'lan') == 'cloud' else 1.025 - .125 * speed
            self.wake.wait(min(interval, max(.08, end - time.monotonic())))
            self.wake.clear()

    def shutdown(self):
        self.close.set()
        self.wake.set()
        self.recovery_wake.set()
        try:
            self.stop("Dashboard shutting down")
        except RuntimeError:
            pass
        self.worker.join(timeout=3)
        self.telemetry_worker.join(timeout=3)
        self.recovery_worker.join(timeout=3)



class HybridEngine(Engine):
    """Select LAN when the phone is on home Wi-Fi, otherwise HTTPS cloud.

    Route is pinned for a running session. On a failed command, session ends;
    we never silently switch to an alternate route and restart output.
    """

    def __init__(self, phone, token, uid, simulate=False):
        self.token = token
        self.uid = uid  # Retained for systemd CLI compatibility, never sent to HTTPS cloud.
        self.cloud_session_uid = None  # Pinned HTTPS callback UID; not the old pi-owner UID.
        self.cloud_fault_utc = None  # Reconnect event must be strictly newer than fault.
        self.https_cloud_enabled = HTTPS_ENABLE_FLAG.is_file()
        self.active_route = "simulation" if simulate else "unknown"
        self.connection_loss_notice = False
        self.cloud_last_success = None
        self.cloud_rejected_507_at = None
        self.cloud_rejected_507_utc = None
        # These records describe server API responses, NEVER physical motor feedback.
        self.cloud_command_record = {'result': 'not_tested', 'action': None, 'at_utc': None, 'code': None, 'http': None}
        self.cloud_api_accept_count = 0
        self.cloud_api_reject_count = 0
        self.local_last_success = None
        super().__init__(phone, simulate=simulate)
        self.keeper_watch = threading.Thread(target=self._keeper_watch_loop, name="keeper-watch", daemon=True)
        self.keeper_watch.start()

    def _paired_status(self):
        """Event-only HTTPS pairing state; NEVER a live Bluetooth heartbeat."""
        return verified_pairing()

    def _keeper_snapshot(self):
        """Compatibility shape for dashboard, sourced from HTTPS callback only.

        'connected' below means *confirmed historical pairing*, NOT that the
        app or motors are online now. Keep 'unverified' true at all times.
        """
        if self.simulate:
            return {"fresh":True,"connected":True,"paired":True,"battery":None,
                    "state":"simulation","age":0,"last_event_utc":None,
                    "last_event_age":0,"unverified":True,"zero_unverified":False,
                    "app_online":None,"message":"Simulation (no real cloud commands)"}
        try:
            p = self._paired_status()
            age = p['age_seconds']
            return {"fresh":True,"connected":True,"paired":True,"battery":None,
                    "state":"https_pairing_confirmed","age":age,
                    "last_event_utc":p['updated_utc'],"last_event_age":age,
                    "unverified":True,"zero_unverified":False,"app_online":None,
                    "message":"HTTPS paired (%s ago); live device connection unknown" %
                              (str(round(age/60))+' min')}
        except PairingError as exc:
            return {"fresh":False,"connected":False,"paired":False,"battery":None,
                    "state":"https_pairing_unavailable","age":None,
                    "last_event_utc":None,"last_event_age":None,"unverified":True,
                    "zero_unverified":False,"app_online":None,
                    "message":"HTTPS pairing unavailable: " + str(exc)}

    def _abort_cloud_session(self, reason):
        with self.state_lock:
            if self.mode == "idle" or self.active_route != "cloud":
                return
            self.connection_loss_notice = True
        try:
            self.stop("Cloud session cancelled: " + reason, fault=True)
        except RuntimeError:
            pass

    def _cloud_pairing_is_recent(self, pair, *, max_age=CLOUD_CALLBACK_MAX_AGE_SECONDS):
        try:
            return (pair.get('uid') == self.cloud_session_uid and
                    type(pair.get('age_seconds')) in (int, float) and
                    0 <= pair['age_seconds'] <= max_age)
        except (AttributeError, TypeError, ValueError):
            return False

    def _send_levels(self, gen, a, b):
        # Fail closed on ageing/cancelled cloud pairing before issuing another
        # motor command. This is only a timeout POLICY; it cannot detect a
        # short outage while callback state remains cached.
        with self.state_lock:
            is_cloud = self.active_route == 'cloud' and self.mode != 'idle'
            uid = self.cloud_session_uid
        if is_cloud:
            try:
                pair = self._paired_status()
            except PairingError as exc:
                raise RuntimeError('Cloud pairing missing during motor session') from exc
            if pair.get('uid') != uid or not self._cloud_pairing_is_recent(pair):
                raise RuntimeError('Cloud pairing expired/changed; cancelling motor session')
        return super()._send_levels(gen, a, b)

    def stop(self, why="Stopped", fault=False, cancel_pending=True):
        with self.state_lock:
            route_cloud = self.active_route == 'cloud'
            was_cloud = route_cloud and self.mode != 'idle'
            if route_cloud:
                self.cloud_fault_utc = datetime.now(timezone.utc)
                self.stop_in_flight += 1  # Hold Start until cloud post-Stop lock is installed.
        try:
            result = super().stop(why, fault=fault, cancel_pending=cancel_pending)
            if was_cloud and not fault:
                # Even when HTTPS Stop returns 200, phone delivery is not proven.
                # Prevent another cloud Start until the user confirms that they
                # have PHYSICALLY POWERED OFF the device. Do not claim an emergency
                # hardware stop or leak current device state.
                with self.state_lock:
                    if not self.fault_latched:
                        self.fault_serial += 1
                        self.fault_latched = True
                        self.fault_route = 'cloud'
                        self.fault_reason = 'Cloud Stop accepted by server; physical motor state unverified'
                        self.routine_cloud_stop_confirm_required = True
                        self.stop_pending = False
                        self.stop_acks = 0
                        self.message = ('Session finished — cloud Stop accepted by server. '
                                        'Device delivery remains unverified.')
                return self.status()
            return result
        finally:
            if route_cloud:
                with self.state_lock:
                    self.stop_in_flight -= 1

    def _keeper_watch_loop(self):
        # Old Socket.IO keeper is DISABLED. An HTTPS callback is not a heartbeat.
        # Watch only for invalidated/replaced pairing identity while running.
        while not self.close.wait(3.0):
            with self.state_lock:
                cloud_running = self.mode != "idle" and self.active_route == "cloud"
                pinned_uid = self.cloud_session_uid
            if cloud_running:
                try:
                    paired = self._paired_status()
                except PairingError:
                    paired = None
                if (not paired or paired.get('uid') != pinned_uid or
                    not self._cloud_pairing_is_recent(paired)):
                    self._abort_cloud_session('HTTPS pairing unavailable, changed, or older than 90s')

    def _local_api(self, payload):
        # The base Engine implementation is the already-tested LAN API.
        return Engine._api(self, payload)

    def _note_cloud_result(self, outcome, action, code=None, http=None):
        # Deliberately omit token, uid, device identifiers and response body.
        safe_action = 'Stop' if action == 'Stop' else 'MotorLevels' if action.startswith('Vibrate') else 'Other'
        with self.state_lock:
            self.cloud_command_record = {
                'result': outcome, 'action': safe_action,
                'code': code if isinstance(code, int) else None,
                'http': http if isinstance(http, int) else None,
                'at_utc': datetime.now(timezone.utc).isoformat(),
            }
            if outcome == 'api_accepted':
                self.cloud_api_accept_count += 1
            elif outcome in ('rejected', 'transport_failed'):
                self.cloud_api_reject_count += 1

    def _cloud_507_blocked(self, keeper):
        # Never clear 507 on a timer. A newly authenticated HTTPS pairing
        # callback must be newer than the rejection.
        with self.state_lock:
            fail_utc = self.cloud_rejected_507_utc
        if fail_utc is None:
            return False
        event_utc=keeper.get('last_event_utc')
        if not (keeper.get('paired') and event_utc):
            return True
        try:
            if datetime.fromisoformat(event_utc.replace('Z','+00:00')) <= datetime.fromisoformat(fail_utc.replace('Z','+00:00')):
                return True
        except (TypeError, ValueError):
            return True
        with self.state_lock:
            if self.cloud_rejected_507_utc == fail_utc:
                self.cloud_rejected_507_utc = None
                self.cloud_rejected_507_at = None
        return False

    def _cloud_api(self, payload):
        if not self.token:
            raise RuntimeError("Cloud token is not configured")
        if not self.cloud_session_uid:
            raise RuntimeError("No pinned, verified HTTPS pairing UID; refusing cloud command")
        body = {**payload, "token": self.token, "uid": self.cloud_session_uid}
        action = str(payload.get('action', ''))
        try:
            proc = subprocess.run(
                ["curl", "-q", "-sS", "--proto", "=https", "--max-redirs", "0",
                 "--connect-timeout", "4", "--max-time", "9",
                 "-H", "Content-Type: application/json", "--data-binary", "@-",
                 "-w", "\nHTTP_STATUS:%{http_code}", CLOUD_ENDPOINT],
                input=json.dumps(body), text=True, capture_output=True, timeout=12,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._note_cloud_result('transport_failed', action)
            raise RuntimeError("Lovense cloud request timed out or curl is missing") from exc
        if proc.returncode != 0:
            self._note_cloud_result('transport_failed', action)
            raise RuntimeError(f"Lovense cloud connection failed (curl exit {proc.returncode})")
        try:
            raw, status = proc.stdout.rsplit("\nHTTP_STATUS:", 1)
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("Not an object")
            code = result.get("code")
        except (ValueError, AttributeError, TypeError) as exc:
            self._note_cloud_result('transport_failed', action)
            raise RuntimeError("Lovense cloud returned an unexpected response") from exc
        try:
            http_num = int(status.strip())
        except (ValueError, TypeError):
            http_num = None
        if status.strip() != "200" or type(code) is not int or code != 200:
            # Never log raw response/credentials. Error 507 is latched until
            # newer *device* evidence arrives, NOT merely for 90 seconds.
            self._note_cloud_result('rejected', action, code=code, http=http_num)
            if code == 507:
                with self.state_lock:
                    self.cloud_rejected_507_at = time.monotonic()
                    self.cloud_rejected_507_utc = datetime.now(timezone.utc).isoformat()
            raise RuntimeError(f"Lovense cloud rejected command (HTTP {status.strip()}, code {code})")
        self._note_cloud_result('api_accepted', action, code=code, http=http_num)
        with self.state_lock:
            self.cloud_last_success = time.monotonic()
        return result

    def _api(self, payload):
        if self.simulate:
            return self._local_api(payload)
        if payload.get("command") == "GetToys":
            return self._local_api(payload)
        if self.active_route == "cloud":
            return self._cloud_api(payload)
        return self._local_api(payload)

    def _get_local_toy(self):
        # A connectivity check, not a motor command. Doesn't hold motor IO lock.
        result = self._local_api({"command": "GetToys"})
        toy = self._extract_toy(result)
        if not toy or str(toy.get("status", "1")).lower() not in ("1", "true", "connected"):
            raise RuntimeError("No connected toy at home LAN address")
        model = str(toy.get("name") or toy.get("model") or "").lower().strip()
        if "".join(ch for ch in model if ch.isalnum()) not in ("edge", "edge2"):
            raise RuntimeError("Home LAN did not confirm an Edge 2")
        return toy

    def _cloud_start_readiness(self, keeper):
        # Callback pairing is historic. A STOP-only HTTPS round trip immediately
        # before Start/Test is the real-time SERVER ACCEPTANCE preflight.
        if not self.https_cloud_enabled:
            return False, 'Experimental HTTPS cloud is disabled until off-body pilot succeeds.'
        if not self.token:
            return False, 'Cloud developer token missing.'
        if self._cloud_507_blocked(keeper):
            return False, 'Cloud rejected code 507; re-pair HTTPS and retry STOP-only check.'
        if not keeper.get('paired'):
            return False, keeper.get('message', 'HTTPS pairing missing')
        age = keeper.get('last_event_age')
        if type(age) not in (int, float) or age < 0 or age > CLOUD_CALLBACK_MAX_AGE_SECONDS:
            return False, 'HTTPS callback older than 90s; re-pair/reconnect before Start (not a heartbeat).'
        return True, 'Recent HTTPS callback is NOT a live signal; Stop-only preflight required.'

    def _cloud_stop_preflight(self):
        # Stop request is deliberately sent BEFORE pinning the cloud session.
        # This checks Lovense SERVER acceptance only; not physical stopping.
        return self._cloud_api({"command":"Function", "action":"Stop",
                                "timeSec":0, "stopPrevious":1, "apiVer":1})

    def _choose_route(self):
        # Only return a proposed route. Do not change the pinned route before
        # Start commits, or a concurrent STOP could be sent to the wrong API.
        if self.simulate:
            return "simulation"
        try:
            self._get_local_toy()
            route = "lan"
        except RuntimeError:
            if not self.token:
                raise RuntimeError("Home LAN is unavailable and cloud token is not configured") from None
            keeper = self._keeper_snapshot()
            allowed, reason = self._cloud_start_readiness(keeper)
            if not allowed:
                raise RuntimeError(reason) from None
            try:
                pair = self._paired_status()
            except PairingError as exc:
                raise RuntimeError('HTTPS pairing unavailable; re-pair before cloud use') from exc
            # Stop pins the old route until Start commits, so never change
            # active_route during discovery/preflight.
            with self.state_lock:
                self.cloud_session_uid = pair['uid']
            self._cloud_stop_preflight()
            route = "cloud"
        return route

    def start(self, body):
        with self.state_lock:
            if self.fault_latched or self.close.is_set() or self.stop_in_flight:
                raise RuntimeError("Connection fault locked or Stop pending: cannot Start")
            epoch = self.stop_epoch
            was_running = self.mode != "idle"
        if was_running:
            return self.switch_pattern(body)
        route = self._choose_route()
        if route == 'cloud':
            if type(body.get('untilStopped', False)) is not bool:
                raise ValueError('Invalid unlimited timer flag')
            requested = limited_number(body.get('minutes', 5), .25, 120)
            if requested * 60 > CLOUD_MAX_SESSION_SECONDS:
                raise RuntimeError('Cloud timed sessions cannot exceed 120 minutes.')
            extended = body.get('untilStopped', False) or requested * 60 > 60
            if extended and body.get('acceptExtendedCloudRisk') is not True:
                raise RuntimeError('Extended cloud session requires confirming the cloud safety limitations. Stop delivery may be unverified.')
        result = super().start(body, expected_stop_epoch=epoch, route=route)
        with self.state_lock:
            if self.stop_epoch == epoch and self.mode != "idle":
                self.connection_loss_notice = False
                self.message = ("Running via Home Wi-Fi" if route == "lan" else
                                "Cloud pattern scheduled; physical delivery not verified")
        return self.status()

    def switch_pattern(self, body):
        with self.state_lock:
            route = self.active_route
            pinned_uid = self.cloud_session_uid
            running = self.mode != 'idle'
        if not running:
            raise RuntimeError('No active session to switch')
        if route == 'cloud':
            try:
                pair = self._paired_status()
                if pair.get('uid') != pinned_uid or not self._cloud_pairing_is_recent(pair):
                    raise PairingError('Cloud pairing no longer fresh')
            except PairingError as exc:
                self._abort_cloud_session('Cloud pairing changed/expired during pattern switch')
                raise RuntimeError('Cloud session stopped: pairing unavailable') from exc
        return super().switch_pattern(body)

    def test(self):
        with self.state_lock:
            if self.fault_latched or self.close.is_set() or self.stop_in_flight:
                raise RuntimeError("Connection fault locked or Stop pending: cannot Test")
            epoch = self.stop_epoch
            was_running = self.mode != "idle"
        if was_running:
            self.stop("Starting motor test", cancel_pending=False)
        route = self._choose_route()
        result = super().test(expected_stop_epoch=epoch, route=route)
        return self.status()

    def acknowledge_fault(self, physical_off=False):
        with self.state_lock:
            cloud_fault = self.fault_latched and self.fault_route == 'cloud'
            if cloud_fault:
                if physical_off is not True:
                    raise RuntimeError('Cloud fault: explicitly confirm PHYSICAL POWER OFF to re-arm')
                if self.mode != 'idle' or self.stop_in_flight:
                    raise RuntimeError('Cannot re-arm during a running or stopping session')
                # Physical OFF is a user declaration, not an API assertion.
                self.stop_epoch += 1
                self.fault_serial += 1  # Cancel queued recovery activity.
                self.stop_pending = False
                self.stop_acks = 0
                self.fault_latched = False
                self.fault_route = None
                self.fault_reason = ''
                self.routine_cloud_stop_confirm_required = False
                self.last_stop_error = ''
                self.connection_loss_notice = False
                self.message = 'User confirmed physical power OFF. Cloud re-arm allowed; live status still unverified.'
        if not cloud_fault:
            super().acknowledge_fault()
            with self.state_lock:
                if not self.fault_latched:
                    self.connection_loss_notice = False
        return self.status()

    def _recovery_ready(self, route):
        # Never switch transport during fault recovery. Returning to a cloud
        # READY status is not evidence that a failed LAN STOP reached the toy.
        if route == "lan":
            self._get_local_toy()
            return True
        if route == "cloud":
            # No cloud heartbeat exists. Retry STOP only after a *new*
            # authenticated callback since the fault, and never clear a cloud
            # fault on ACK alone. Physical power-off confirmation is required.
            try:
                pair = self._paired_status()
                event = datetime.fromisoformat(pair['updated_utc'].replace('Z', '+00:00'))
                with self.state_lock:
                    fault_utc = self.cloud_fault_utc
                return (self._cloud_pairing_is_recent(pair) and
                        fault_utc is not None and event > fault_utc)
            except (PairingError, ValueError, TypeError, KeyError, AttributeError):
                return False
        return self.simulate

    def refresh_toys(self):
        if self.simulate:
            return super().refresh_toys()
        with self.state_lock:
            route = self.active_route
            pinned = self.mode != "idle" or self.fault_latched or self.stop_in_flight > 0
        # Cloud callback is cached pairing evidence, NOT a live toy status.
        # Never use LAN GetToys to mask a cloud-session failure (or vice versa).
        if pinned and route == "cloud":
            keeper = self._keeper_snapshot()
            with self.state_lock:
                self.last_telemetry = time.monotonic()
                self.toy_connected = bool(keeper["connected"])
                self.last_device_error = "" if keeper["connected"] else keeper["message"]
            return self.status()
        try:
            toy = self._get_local_toy()
        except RuntimeError as exc:
            keeper = None if pinned else self._keeper_snapshot()
            with self.state_lock:
                self.last_telemetry = time.monotonic()
                if pinned:
                    # Never disguise loss of pinned LAN route by cloud status.
                    self.toy_connected = False
                    self.last_device_error = str(exc)
                else:
                    self.toy_connected = keeper["connected"] if self.token else False
                    self.last_device_error = keeper["message"] if self.token else str(exc)
                    self.active_route = "cloud" if self.token and self.https_cloud_enabled else "unavailable"
            return self.status()
        with self.state_lock:
            self.last_telemetry = time.monotonic()
            self.local_last_success = time.monotonic()
            self.toy_connected = True
            self.last_device_error = ""
            raw_battery = toy.get("battery")
            try:
                val = int(raw_battery)
                if 0 <= val <= 100:
                    self.battery = val
            except (TypeError, ValueError):
                pass
            self.device_name = "Edge 2"
            if not pinned:
                self.active_route = "lan"
        return self.status()

    def status(self):
        result = super().status()
        keeper = self._keeper_snapshot()
        # Readiness may clear a 507 latch only after a NEW connected device event.
        # This must run outside the state lock (the helper acquires it).
        cloud_allowed, cloud_reason = self._cloud_start_readiness(keeper)
        with self.state_lock:
            blocked_507 = self.cloud_rejected_507_utc is not None
            route = self.active_route
            result["connectionMode"] = route
            result["profile"] = "hybrid"
            result["cloudConfigured"] = bool(self.token)
            result["cloudCommandAccepted"] = self.cloud_last_success is not None
            result["cloudConnected"] = False  # No live heartbeat from HTTPS callback.
            result["cloudPairingConfirmed"] = bool(self.token and keeper.get("paired", False))
            result["cloudExperimentalEnabled"] = self.https_cloud_enabled
            result["cloudLastCommand"] = dict(self.cloud_command_record)
            result["cloudApiAcceptedTotal"] = self.cloud_api_accept_count
            result["cloudApiRejectedTotal"] = self.cloud_api_reject_count
            result["cloudPhysicalDeliveryVerified"] = False
            result["cloudBlockedAfter507"] = blocked_507
            result["cloudCanStart"] = bool(self.token and cloud_allowed and not self.fault_latched and not self.stop_pending)
            result["cloudStartReason"] = cloud_reason if self.token else 'Cloud not configured'
            result["cloudDeviceTelemetryStale"] = True
            result["cloudStatusUnverified"] = True
            result["cloudCallbackPolicyMaxAgeSec"] = CLOUD_CALLBACK_MAX_AGE_SECONDS
            result["cloudSessionLimitSec"] = CLOUD_MAX_SESSION_SECONDS
            result["cloudRequiresPhysicalOff"] = bool(self.fault_latched and self.fault_route == 'cloud')
            result["cloudRoutineStopConfirmRequired"] = bool(
                self.fault_latched and self.fault_route == 'cloud' and
                not self.stop_pending and self.routine_cloud_stop_confirm_required)
            result["cloudLastErrorCode"] = 507 if blocked_507 else None
            result["cloudAppOnline"] = keeper["app_online"]
            result["cloudDeviceReportAgeSec"] = keeper["last_event_age"]
            result["cloudBatteryUnverifiedZero"] = keeper["zero_unverified"]
            result["cloudKeeperState"] = keeper["state"]
            result["cloudKeeperAgeSec"] = keeper["age"]
            result["lastCloudDeviceEventUTC"] = keeper["last_event_utc"]
            result["cloudKeeperMessage"] = ("Lovense returned 507: re-pair HTTPS before next cloud session" if blocked_507
                                            else keeper["message"])
            result["connectionWarning"] = (self.connection_loss_notice or blocked_507 or
                                           (self.mode != "idle" and route == "cloud" and not keeper.get("paired", False)))
            if route != "lan":
                result["battery"] = keeper["battery"]
                result["batterySource"] = None  # Callback does not provide live battery.
                result["batteryIsStale"] = keeper["unverified"] or not keeper["connected"]
                result["toyConnected"] = None  # HTTPS pairing does NOT verify physical connection.
                result["lastDeviceError"] = result["cloudKeeperMessage"]
                result["lastDeviceCheckSec"] = keeper["age"]
            else:
                result["batterySource"] = "Home LAN" if self.battery is not None else None
                result["batteryIsStale"] = self.toy_connected is not True
                result["lastCloudDeviceEventUTC"] = keeper["last_event_utc"]
        return result

    def shutdown(self):
        super().shutdown()
        self.keeper_watch.join(timeout=3)


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0a101b"><title>PulseDirector · LAN Studio</title>
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',Arial,sans-serif;color:#edf0fc;background:#0a101b;color-scheme:dark;--bg:#0a101b;--panel:#141d2b;--border:#2b3950;--dim:#93a1bc;--accent:#bba8ff;--teal:#80e9cd;--rose:#ff849a}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 50% -13%,#42376191 0,transparent 49%),radial-gradient(ellipse at 99% 14%,#0f555339 0,transparent 34%),#0a101b}
button,input,select{font:inherit}button{cursor:pointer;touch-action:manipulation}
button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #a6f4e1;outline-offset:3px}
.wrap{max-width:1080px;margin:0 auto;padding:30px 20px 110px}
.top{display:flex;justify-content:space-between;gap:14px;align-items:center;margin-bottom:28px}
.mark{display:flex;align-items:center;gap:12px}
.logo{width:49px;height:49px;display:grid;place-items:center;background:linear-gradient(140deg,#a897ff,#82e6d0);color:#101323;border-radius:16px;font-size:27px;font-weight:900;box-shadow:0 8px 30px #bba8ff3b}
.overline,.eyebrow,.live-label{color:#9ea9c1;font-size:10px;font-weight:850;letter-spacing:2px;text-transform:uppercase}
.title{font-size:25px;font-weight:860;letter-spacing:-1px;line-height:1.15}.brand-accent{color:#c4b6ff}.version{font-size:10px;letter-spacing:0;vertical-align:super;color:#b9c3db;margin-left:8px;font-weight:600}
.tiny,.muted{font-size:12px;color:#9eacc5;line-height:1.45}
.chip{display:flex;align-items:center;gap:9px;border:1px solid #40516d;background:#182235;border-radius:30px;padding:10px 14px;white-space:nowrap;font-weight:700;font-size:12px}
.dot{display:inline-block;width:9px;height:9px;background:#7e90ad;border-radius:50%}.dot.live{background:var(--teal);box-shadow:0 0 14px #80e9cd99}
.panel{background:linear-gradient(155deg,#192437,#121b2a);border:1px solid var(--border);border-radius:22px;padding:24px;margin:0 0 17px;box-shadow:0 14px 40px #060a1440}
.panel:first-of-type{background:linear-gradient(120deg,#352c50,#182438 54%,#152f35);border-color:#5b527b}
.eyebrow{margin:0 0 15px;color:#bbaff7}.status-overline{color:#8b96b0}
.status-box{display:flex;align-items:center;justify-content:space-between;gap:25px}
.status-name{font-size:clamp(23px,3.7vw,37px);font-weight:850;letter-spacing:-1.25px;line-height:1.12;margin:0 0 9px}
.status-message{max-width:610px;color:#c3cadd;font-size:13px;overflow-wrap:anywhere;line-height:1.5}
.timebox{text-align:right;min-width:100px}.countdown{font-variant-numeric:tabular-nums;font-size:31px;font-weight:850;letter-spacing:-1px}
.progress-track,.energy-track{height:6px;width:100%;background:#ffffff17;border-radius:22px;overflow:hidden;margin-top:21px}.progress-fill{height:100%;width:0%;background:linear-gradient(90deg,#9e8bff,#82e6d0);transition:width .3s}.scene-strip{display:flex;flex-wrap:wrap;gap:9px;margin:14px 0 4px}.scene-chip{border:1px solid #7363986b;background:#8172b12a;padding:7px 10px;border-radius:20px;font-weight:750;font-size:11px;color:#ddd1ff}.scene-chip.subtle{color:#b4d9d3;background:#479f8c14;border-color:#479f8c52}
.stop{width:100%;margin-top:16px;border:1px solid #ffafbd;background:linear-gradient(105deg,#fa788f,#ffb1a7);color:#281322;font-size:16px;font-weight:900;letter-spacing:.4px;border-radius:13px;padding:16px;box-shadow:0 8px 21px #fb718542}.stop:hover{filter:brightness(1.07)}
.sectionhead{display:flex;align-items:end;justify-content:space-between;gap:12px;margin:0 0 18px}.sectionhead h2,h2{font-size:18px;font-weight:800;margin:0;letter-spacing:-.4px}.sub{color:#98a8c2;font-size:12px}
.stats-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px}
.stat{background:#0e1725a8;border:1px solid #293a50;border-radius:14px;padding:15px;min-width:0}.stat-label{font-size:11px;color:#98a8c3;margin-bottom:10px}.stat-number{font-variant-numeric:tabular-nums;font-size:26px;font-weight:850;overflow-wrap:anywhere}.stat-number.small-number{font-size:17px}.online{color:#82e9cb}.danger{color:#ff9bb0}
.battery-meter,.meter{height:7px;background:#344257;border-radius:22px;overflow:hidden;margin:10px 0 7px}.battery-fill{height:100%;width:0;background:linear-gradient(90deg,#63c2a8,#b2eed1);transition:width .4s}
.stats-bottom{margin-top:15px;display:flex;gap:12px 25px;flex-wrap:wrap;color:#aebbd0;font-size:12px}.stats-bottom b{color:#d4ddf2;font-variant-numeric:tabular-nums}
.cloud-detail{border-top:1px solid #30415a;margin-top:16px;padding-top:16px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:12px;color:#c1cce0}.cloud-detail>div:first-child{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.cloud-indicator{width:8px;height:8px;background:#72829a;border-radius:50%}.cloud-indicator.ok{background:#80e9cd}.cloud-indicator.bad{background:#fb8798}.warning-banner{margin-top:13px;border:1px solid #cb6d82;color:#ffd4d8;background:#69344d77;padding:12px;border-radius:12px;font-size:12px;line-height:1.5}.safety-fault{border:2px solid #ff647e;background:#5b1425e0;color:#fff0f3;font-size:14px;font-weight:700}.safety-fault button{margin-top:10px;width:100%}.safety-fault button:disabled{opacity:.5;cursor:not-allowed}
/* Routine cloud confirmation appears only when another session is requested. */
.safety-fault.routine-confirmation{border:1px solid #63748d;background:#202d40;color:#e3ebfa;font-size:13px;font-weight:500}
.safety-fault.routine-confirmation strong{color:#d4efe8;font-size:15px}
.safety-fault.routine-confirmation label{font-weight:650}
.inline-request-error{margin-top:12px;border:1px solid #d98a9a;background:#5d2c3b4d;color:#ffe3e9;padding:10px 12px;border-radius:10px;font-size:13px;line-height:1.5}
.timer-route-hint{font-size:12px;color:#aabbd2;margin-top:8px} 
.modes{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.mode{background:linear-gradient(145deg,#1c2a3c,#152030);border:1px solid #34445c;color:#e7e9fa;border-radius:14px;min-height:102px;text-align:left;padding:14px;display:flex;flex-direction:column;gap:7px;transition:background .13s,border-color .13s,transform .13s}.mode:hover{background:#2b3850;transform:translateY(-1px)}.mode.selected{background:linear-gradient(145deg,#413b67,#223447);border-color:#c1a7ff;box-shadow:inset 0 0 0 1px #b99bff44}.mode.featured-mode{grid-column:span 2;flex-direction:row;flex-wrap:wrap;align-content:center;align-items:center;gap:7px 14px;background:linear-gradient(120deg,#373053,#203b45)}.mode.featured-mode .desc{flex-basis:100%}.mode .sym{font-size:24px;color:#c7b8ff;line-height:1}.mode .txt{font-size:14px;font-weight:780}.mode .desc{font-size:11px;color:#abbad2;line-height:1.4}
.director-feature{background:linear-gradient(150deg,#302e50,#1c2b3b 66%,#182936);border-color:#7667a7}.director-feature h2{font-size:22px}.spark{color:#bdaaff}.director-feature .sub{line-height:1.6;margin-top:9px;max-width:750px}.director-options{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-top:20px}.director-options>div{min-width:0}.director-feature select{width:100%;background:#101d2e;border:1px solid #655f85;border-radius:11px;color:#f0edff;margin:7px 0 0;padding:12px;font-size:13px}.range-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px;font-size:13px}.range-wrap{margin-bottom:24px}.range-wrap:last-child{margin-bottom:0}.duration-presets{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.duration-presets button{border:1px solid #51607e;border-radius:8px;color:#d9e4fc;background:#26374e;padding:7px 10px;cursor:pointer}.unlimited-label{display:flex;gap:10px;align-items:center;margin-top:11px;font-size:12px;color:#d3e4f6}.unlimited-label input{accent-color:#ab9ff3}.value{font-size:12px;font-weight:800;background:#3c365a;color:#ddd0ff;border-radius:8px;padding:6px 9px;font-variant-numeric:tabular-nums}input[type=range]{width:100%;height:26px;accent-color:#b9a3ff;cursor:pointer}
.director-live{margin-top:18px;border:1px solid #6f7da261;background:#101b2cb3;border-radius:15px;padding:18px}.director-live-head{display:flex;justify-content:space-between;align-items:center;gap:10px}.intent-line{margin-top:10px;font-weight:720;font-size:13px;color:#9dedda;letter-spacing:.1px}.scene-value{color:#c9befc;font-size:19px;font-weight:800;text-align:right}.director-live-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px;margin-top:17px}.director-live-grid>div{display:flex;flex-direction:column;gap:6px}.director-live-grid strong{font-size:16px;color:#e4e8f7}.energy-head{display:flex;justify-content:space-between;margin-top:16px;font-size:11px;font-weight:750;color:#b4bed6}.energy-track{margin-top:8px;height:6px}.energy-fill{background:linear-gradient(90deg,#61bda9,#b5a3ff,#ef9ab7);width:0;height:100%;transition:width .3s}
.director-idea{margin-top:13px;border:1px solid #635f8c;background:#38335158;border-radius:12px;padding:12px 14px;color:#c5c3e1;font-size:12px;line-height:1.5}
.rows{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:25px}.start{display:block;width:100%;border:0;border-radius:13px;background:linear-gradient(110deg,#bba8ff,#80dfce);color:#121b29;font-size:16px;font-weight:900;padding:16px;margin-top:15px;box-shadow:0 9px 22px #a0a1e32c}.start:hover{filter:brightness(1.08)}.secondary{background:#233147;color:#e8ebfa;border:1px solid #44516c;border-radius:11px;padding:11px 14px;font-size:13px;font-weight:700}.secondary:hover{background:#344460}.tools{display:flex;flex-wrap:wrap;gap:9px;margin-top:17px}.motor-name{display:flex;justify-content:space-between;gap:8px;align-items:center}.motor-name b{font-size:14px}.motor-read{color:#d0bbff;font-size:13px;font-weight:800}.meter{height:9px}.fill{height:100%;width:0%;background:linear-gradient(90deg,#9887f9,#83e6d4);transition:width .3s}.muted{margin:9px 0 0}.footer{text-align:center;font-size:11px;line-height:1.7;color:#7d8ea8;margin:23px auto;max-width:680px}
.modal{position:fixed;inset:0;z-index:30;background:#080e19ed;display:grid;place-items:center;padding:20px}.login{background:#182338;border:1px solid #4c5576;border-radius:20px;padding:28px;width:100%;max-width:400px}.login h2{font-size:23px}.login input{width:100%;margin:10px 0;padding:13px;background:#0d1625;border:1px solid #586b88;border-radius:11px;color:#fff;font-size:16px}.hide{display:none!important}.error{color:#ffadbb;font-size:12px;min-height:17px}
.stop-dock{position:fixed;bottom:calc(env(safe-area-inset-bottom, 0px) + 11px);right:16px;left:16px;z-index:16;display:none;align-items:center;gap:12px;max-width:460px;margin:auto;background:#152135f2;border:1px solid #a4667b;border-radius:16px;padding:9px 10px 9px 16px;box-shadow:0 9px 35px #050915a0;backdrop-filter:blur(12px);font-size:12px;color:#d6deef}.stop-dock button{margin-left:auto;background:#fc8194;border:0;border-radius:10px;color:#29121f;padding:10px 19px;font-size:13px;font-weight:900}
@media(max-width:760px){.modes{grid-template-columns:repeat(3,minmax(0,1fr))}.director-options{grid-template-columns:repeat(2,minmax(0,1fr))}.stats-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.stop-dock:not(.hide){display:flex}}
@media(max-width:530px){.wrap{padding:17px 12px 110px}.top{margin-bottom:19px}.logo{width:43px;height:43px;border-radius:14px}.title{font-size:21px}.chip{padding:8px 10px;font-size:11px}.panel{padding:17px;border-radius:17px}.status-box{align-items:flex-start}.status-name{font-size:24px}.countdown{font-size:23px}.timebox{min-width:75px}.modes{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.mode{min-height:98px;padding:11px}.mode.featured-mode{grid-column:span 2}.rows,.director-options{grid-template-columns:1fr;gap:11px}.director-live-grid{gap:8px}.director-live-grid strong{font-size:13px}.scene-value{font-size:16px}.sub{font-size:11px}.stats-grid{gap:8px}.stat{padding:12px}.stat-number{font-size:23px}.stat-number.small-number{font-size:15px}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important}}

</style></head><body>
<div class="wrap">
<div class="top"><div class="mark"><div class="logo">✦</div><div><div class="overline">PRIVATE DEVICE STUDIO</div><div class="title">Pulse<span class="brand-accent">Director</span><span class="version">v4.6 dev1</span></div></div></div><div class="chip"><i class="dot" id="dot"></i><span id="pill">Standby</span></div></div>
<section class="panel"><div class="eyebrow">ON AIR <span class="status-overline">/ YOUR SESSION</span></div><div class="status-box"><div><div class="status-name" id="current">Ready to start</div><div class="status-message" id="msg">Connect Lovense Remote on home Wi-Fi and enable Game Mode.</div></div><div class="timebox"><div class="countdown" id="left">00:00</div><div class="tiny" id="timerLabel">remaining</div></div></div>
<div class="progress-track" aria-label="Session progress"><div id="sessionProgress" class="progress-fill"></div></div>
<div class="scene-strip"><span class="scene-chip" id="stageChip">Waiting for session</span><span class="scene-chip subtle" id="sceneChip">Live scene: —</span></div>
<button class="stop" id="stop">■ &nbsp; STOP ALL MOTORS</button><div id="requestError" role="alert" class="inline-request-error hide"></div></section>
<section class="panel stats-panel"><div class="sectionhead"><h2>Live telemetry</h2><span class="sub" id="updated">Checking device…</span></div>
<div class="stats-grid">
<div class="stat"><div class="stat-label">Edge 2 battery</div><div class="stat-number" id="battery">—</div><div class="battery-meter"><div class="battery-fill" id="batteryBar"></div></div><div class="tiny" id="batteryNote">Awaiting device report</div></div>
<div class="stat"><div class="stat-label">Device connection</div><div class="stat-number small-number" id="connection">Checking</div><div class="tiny" id="connectionNote">LAN or cloud status</div></div>
<div class="stat"><div class="stat-label">Session elapsed</div><div class="stat-number" id="elapsed">00:00</div><div class="tiny">This session</div></div>
<div class="stat"><div class="stat-label">Commands sent</div><div class="stat-number" id="commands">0</div><div class="tiny" id="commandsNote">Does not prove physical vibration</div></div>
</div>
<div class="cloud-detail"><div><span class="cloud-indicator" id="cloudDot"></span><strong id="cloudStatus">HTTPS pairing: checking…</strong><span id="cloudAge" class="tiny"></span></div><div class="tiny" id="lastSeen">Last Lovense report: —</div></div>
<div class="director-idea" id="cloudApiDetail" role="status">Cloud API diagnostic: awaiting command. API acceptance does not prove motor movement.</div>
<div class="warning-banner safety-fault hide" id="safetyFault" role="alert"><strong id="safetyTitle">CONNECTION FAULT — PHYSICAL MOTOR STATE UNKNOWN</strong><p id="safetyFaultText">Automatic Stop pending. Use the toy's physical power button if needed.</p><label id="cloudOffLabel" class="hide"><input type="checkbox" id="cloudOffConfirm"> I've physically switched off the Edge 2. A server response alone cannot confirm it.</label><button type="button" class="secondary" id="ackFault" disabled>Acknowledge after checking physical device</button></div>
<div class="warning-banner hide" id="connectionWarning" role="alert">Cloud transport fault: physical Stop is unverified. POWER OFF Edge 2 and acknowledge before restarting.</div>
<div class="stats-bottom"><span>Motor 1 · prostate-facing: <b id="level1">0 / 20</b></span><span>Motor 2 · perineum: <b id="level2">0 / 20</b></span></div>
</section>
<section class="panel" id="pairingPanel"><div class="sectionhead"><h2>Cloud connection</h2><span class="sub">Reconnect Lovense Remote without PuTTY</span></div>
<p class="muted">If HTTPS Cloud pairing expires or you switch modes, use Reconnect. This will not start motors or change your pairing identity. The QR is for Lovense Remote, not for logging in to PulseDirector.</p>
<div class="tools"><button type="button" class="secondary" id="pairQrButton">Show pairing QR or code</button><button type="button" class="secondary hide" id="pairQrHide">Hide pairing details</button></div>
<div id="pairQrContent" class="hide" style="margin-top:14px" aria-live="polite">
<p class="tiny"><b>On this phone:</b> In Lovense Remote, open the QR scanner and choose <b>Input QR Code Number</b>.</p>
<div id="pairQrCodeArea" class="hide"><label for="pairQrCode" class="tiny">Pairing code</label><div class="tools"><input id="pairQrCode" type="text" readonly autocomplete="off" spellcheck="false" aria-label="Temporary Lovense pairing code" style="font-weight:750;letter-spacing:2px;font-size:20px;max-width:210px"/><button type="button" class="secondary" id="pairQrCopy">Copy code</button></div></div>
<p class="tiny" id="pairQrNoCode" style="display:none">Lovense did not provide a manual code; use the QR image on another screen.</p>
<p class="tiny">On a second screen: scan this QR in Lovense Remote.</p>
<img id="pairQrImage" alt="Lovense Remote pairing QR code" width="240" height="240" style="max-width:100%;height:auto;background:#fff;border-radius:9px;padding:6px"/>
<p class="tiny" id="pairQrExpires">The pairing details expire about four hours after generation. Treat the code as private.</p></div>
<p class="tiny" id="pairQrMessage" role="status">No new pairing requested. Last paired status is shown above; it may be cached.</p></section>
<section class="panel"><div class="sectionhead"><h2>Pattern library</h2><span class="sub">20 ways to play</span></div><div class="modes" id="modes">
<button class="mode selected featured-mode" data-mode="autonomous"><span class="sym">✦</span><span class="txt">Autonomous Director</span><span class="desc">Makes fresh decisions; no repeating pattern list</span></button>
<button class="mode" data-mode="wave"><span class="sym">∿</span><span class="txt">Wave</span><span class="desc">Motor 1 leads; Motor 2 follows</span></button>
<button class="mode" data-mode="pulse"><span class="sym">◉</span><span class="txt">Pulse</span><span class="desc">Overlapping primary-led bursts</span></button>
<button class="mode" data-mode="alternate"><span class="sym">⇄</span><span class="txt">Alternate</span><span class="desc">Longer Motor 1, then Motor 2</span></button>
<button class="mode" data-mode="chase"><span class="sym">↝</span><span class="txt">Chase</span><span class="desc">Primary, both, secondary, rest</span></button>
<button class="mode" data-mode="sync"><span class="sym">≈</span><span class="txt">Sync</span><span class="desc">Both rise and fall together</span></button>
<button class="mode" data-mode="ramp"><span class="sym">⌁</span><span class="txt">Ramp</span><span class="desc">Smooth rise with delayed accent</span></button>
<button class="mode" data-mode="anchor"><span class="sym">◈</span><span class="txt">Anchor</span><span class="desc">Steady Motor 1 with Motor 2 accents</span></button>
<button class="mode" data-mode="heartbeat"><span class="sym">♥</span><span class="txt">Heartbeat</span><span class="desc">Two Motor 1 pulses, Motor 2 replies</span></button>
<button class="mode" data-mode="orbit"><span class="sym">◎</span><span class="txt">Orbit</span><span class="desc">Different waves; Motor 1 leads</span></button>
<button class="mode" data-mode="cascade"><span class="sym">↠</span><span class="txt">Cascade</span><span class="desc">Motor 1 wave followed by Motor 2</span></button>
<button class="mode" data-mode="flutter"><span class="sym">❋</span><span class="txt">Flutter</span><span class="desc">Steady Motor 1 with spaced accents</span></button>
<button class="mode" data-mode="tide"><span class="sym">≋</span><span class="txt">Tide</span><span class="desc">Long offset swells across both</span></button>
<button class="mode" data-mode="echo"><span class="sym">↳</span><span class="txt">Echo</span><span class="desc">Motor 2 answers after Motor 1</span></button>
<button class="mode" data-mode="drift"><span class="sym">◌</span><span class="txt">Drift</span><span class="desc">Long, offset waves</span></button>
<button class="mode" data-mode="steps"><span class="sym">▥</span><span class="txt">Steps</span><span class="desc">Alternating intensity plateaus</span></button>
<button class="mode" data-mode="ripple"><span class="sym">≋</span><span class="txt">Ripple</span><span class="desc">Layered complementary waves</span></button>
<button class="mode" data-mode="random"><span class="sym">✳</span><span class="txt">Random Mix</span><span class="desc">Shuffles 16 patterns every ~18 sec</span></button>
<button class="mode" data-mode="motor1"><span class="sym">①</span><span class="txt">Motor 1</span><span class="desc">Run only the first motor</span></button>
<button class="mode" data-mode="motor2"><span class="sym">②</span><span class="txt">Motor 2</span><span class="desc">Run only the second motor</span></button>
</div></section>
<section class="panel director-feature" id="directorPanel"><div class="eyebrow">INTELLIGENT SEQUENCING · 100% LOCAL</div><h2>Autonomous Director <span class="spark">✦</span></h2><p class="sub">Makes deliberate moves, sometimes returns to an earlier theme, and varies holds and short resets. No person, sensory feedback or cloud AI is involved.</p>
<div class="director-options">
<div><label for="directorStyle" class="tiny">Behaviour</label><select id="directorStyle"><option value="confident" selected>Confident · deliberate, stronger moves</option><option value="unpredictable">Unpredictable · balanced variety</option><option value="patient">Patient · longer phases</option><option value="playful">Playful · more back-and-forth</option><option value="progressive">Progressive · gradual build</option></select></div>
<div><label for="directorFlow" class="tiny">Session flow</label><select id="directorFlow"><option value="driving" selected>High energy · stronger, longer phases</option><option value="balanced">Balanced · steady variety</option><option value="build">Build · gradual climb</option><option value="waves">Waves · rolling energy arcs</option></select></div>
<div><div class="range-head"><label for="surprise">Surprise level</label><span class="value" id="surpriseVal">4 / 5</span></div><input id="surprise" type="range" min="1" max="5" step="1" value="4"></div>
</div><div class="director-live" aria-live="off">
<div class="director-live-head"><span class="live-label">DIRECTOR LIVE</span><span class="scene-value" id="sceneName">Waiting to start</span></div>
<div class="intent-line" id="intentLine" aria-live="polite">Choosing the next move</div>
<div class="director-live-grid"><div><span class="tiny">Session chapter</span><strong id="directorPhase">—</strong></div><div><span class="tiny">Scene countdown</span><strong id="sceneTime">—</strong></div><div><span class="tiny">New decisions</span><strong id="decisionCount">0</strong></div></div>
<div class="energy-head"><span>Energy profile</span><span id="energyVal">—</span></div><div class="energy-track"><div class="energy-fill" id="energyBar"></div></div>
</div><div class="director-idea" id="directorInfo">Director chooses each new move during the session. Maximum intensity, duration and Motor 2 contribution always remain bounded by your settings.</div></section>
<section class="panel"><div class="sectionhead"><h2>Session settings</h2><span class="sub">Presets and seamless pattern changes</span></div>
<div class="rows"><div><div class="range-wrap"><div class="range-head"><label for="max">Maximum intensity</label><span class="value" id="maxVal">10 / 20</span></div><input id="max" type="range" min="1" max="20" value="10"></div><div class="range-wrap"><div class="range-head"><label for="speed">Pattern speed</label><span class="value" id="speedVal">3 / 5</span></div><input id="speed" type="range" min="1" max="5" value="3"></div></div>
<div><div class="range-wrap"><div class="range-head"><label for="support">Motor 2 contribution</label><span class="value" id="supportVal">65%</span></div><input id="support" type="range" min="0" max="100" step="5" value="65"><p class="muted">Applies to the patterns above. Motor 1 leads; Motor 2 adds perineum-side accents. 100% keeps full programmed Motor 2 strength. Manual controls are unchanged.</p></div><div class="range-wrap"><div class="range-head"><label for="minutes">Session timer</label><span class="value" id="minutesVal">5 min</span></div><input id="minutes" type="range" min="0.5" max="120" step="0.5" value="5">
<div class="duration-presets" id="durationPresets"><button type="button" data-duration="5">5m</button><button type="button" data-duration="15">15m</button><button type="button" data-duration="30">30m</button><button type="button" data-duration="60">60m</button><button type="button" data-duration="120">120m</button></div>
<label class="unlimited-label" id="unlimitedLabel"><input id="untilStopped" type="checkbox"> Until I press Stop</label>
<p class="timer-route-hint" id="timerHint">30 seconds to 120 minutes, or Until Stopped.</p>
<div id="extendedCloudWarning" class="timer-route-hint hide" role="note"><strong>Experimental long cloud sessions</strong><p>Authenticated Lovense callbacks must keep arriving within 90 seconds. If they stop, PulseDirector will cancel and attempt Stop, but cloud acknowledgements do not prove physical delivery. Keep the physical power button accessible. Never rely on software Stop during an outage.</p><label><input id="acceptExtendedCloudRisk" type="checkbox"> I understand and want to allow extended cloud sessions (over 1 minute or Until Stopped).</label></div>
</div><p class="muted">Timed sessions stop at the deadline. Cloud Stop acknowledgement is requested before your next session; a cloud connection interruption may prevent physical Stop.</p></div></div>
<button class="start" id="start">▶ &nbsp; START AUTONOMOUS DIRECTOR</button><p class="muted">During a running session, selecting a different pattern and pressing this button switches patterns without restarting the session or its timer.</p>
</section>
<section class="panel"><div class="sectionhead"><h2>Individual motors</h2><span class="sub">Sliders enter Manual mode</span></div><div class="rows"><div class="range-wrap"><div class="motor-name"><b>Motor 1 · prostate-facing</b><span class="motor-read" id="m1Val">4 / 20</span></div><input id="m1" type="range" min="0" max="20" value="4"><div class="meter"><div class="fill" id="bar1"></div></div></div><div class="range-wrap"><div class="motor-name"><b>Motor 2 · perineum</b><span class="motor-read" id="m2Val">4 / 20</span></div><input id="m2" type="range" min="0" max="20" value="4"><div class="meter"><div class="fill" id="bar2"></div></div></div></div><p class="muted">Moving either slider during a session changes to Manual without resetting the session timer. Levels remain capped by Maximum intensity.</p><div class="tools"><button class="secondary" id="manual">▶ Run manual levels</button><button class="secondary" id="test">Test both motors (7 sec)</button><button class="secondary" id="check">Check connection</button></div></section>
<p class="footer">PulseDirector v4.6 unified dev2 · LAN or optional HTTPS hybrid · Experimental cloud integration; off-body testing required.<br>WireGuard keeps your dashboard private when away from home. Never forward port 8765 to the public internet.</p>
</div>
<div class="stop-dock hide" id="stopDock"><span>Session running</span><button type="button" id="dockStop" aria-label="Stop all motors immediately">■ STOP ALL</button></div>
<div class="modal" id="login"><form class="login" id="loginForm"><div class="overline">LOCAL DEVICE CONTROL</div><h2 style="margin:12px 0 7px">Unlock dashboard</h2><p class="muted">Enter the access key shown in the Raspberry Pi terminal on first launch. It is also saved in <code>~/edge-ai/.edge_dashboard_key</code>.</p><label class="tiny" for="key">Access key</label><input id="key" type="password" autocomplete="off" required placeholder="Paste your access key"><button class="start" type="submit">Unlock controls</button><div class="error" id="loginError"></div></form></div>
<script>
(()=>{'use strict';
const $=id=>document.getElementById(id);
let key=sessionStorage.getItem('edgeKey')||'',mode='autonomous',lastRunning=false,sliderTimer=null,pending=false,lastCloudOffRequired=false,lastStopPending=false;
let routineConfirmRequired=false,routineConfirmExpanded=false,lastStatus=null,priorGenuineFault=false;
// Preserve LAN duration while a limited HTTPS cloud route is selected.
let cloudTimerLimited=false,stickyError='';
const modes=[...document.querySelectorAll('.mode')];
const labels={idle:'Ready to start',autonomous:'Autonomous Director',wave:'Wave',pulse:'Pulse',alternate:'Alternate',chase:'Chase',sync:'Sync',ramp:'Ramp',anchor:'Anchor',heartbeat:'Heartbeat',orbit:'Orbit',cascade:'Cascade',flutter:'Flutter',tide:'Tide',echo:'Echo',drift:'Drift',steps:'Steps',ripple:'Ripple',random:'Random Mix',motor1:'Motor 1',motor2:'Motor 2',manual:'Manual Control',test:'Motor Test'};
function updateStartButton(){const name=mode==='autonomous'?'AUTONOMOUS DIRECTOR':(labels[mode]||mode).toUpperCase();$('start').textContent=lastRunning?'↪  SWITCH TO '+name:'▶  START '+name}
function select(name){mode=name;modes.forEach(b=>b.classList.toggle('selected',b.dataset.mode===name));$('directorPanel').classList.toggle('hide',name!=='autonomous');updateStartButton()}
modes.forEach(b=>b.addEventListener('click',()=>select(b.dataset.mode)));
function settings(m=''){return {mode:m||mode,max:Number($('max').value),speed:Number($('speed').value),support:Number($('support').value),minutes:Number($('minutes').value),untilStopped:$('untilStopped').checked,acceptExtendedCloudRisk:$('acceptExtendedCloudRisk').checked,motor1:Number($('m1').value),motor2:Number($('m2').value),style:$('directorStyle').value,flow:$('directorFlow').value,surprise:Number($('surprise').value)}}
function refreshValues(){for(const [id,suffix] of [['max',' / 20'],['speed',' / 5'],['support','%'],['minutes',' min'],['m1',' / 20'],['m2',' / 20'],['surprise',' / 5']]) $(id+'Val').textContent=$(id).value+suffix}
['max','speed','support','minutes','m1','m2','surprise'].forEach(id=>$(id).addEventListener('input',refreshValues));
$('untilStopped').addEventListener('change',()=>{refreshValues()});
[...document.querySelectorAll('[data-duration]')].forEach(b=>b.addEventListener('click',()=>{$('untilStopped').checked=false;$('minutes').value=b.dataset.duration;refreshValues()}));
const origRefreshValues=refreshValues;refreshValues=function(){origRefreshValues();if($('untilStopped').checked)$('minutesVal').textContent='Until Stop';};refreshValues();
function syncTimerRoute(s){
  const cloud=s.connectionMode==='cloud'&&s.cloudExperimentalEnabled===true;
  cloudTimerLimited=cloud; // cloud flag retained for compatibility; duration is no longer clamped
  $('minutes').max='120';
  $('untilStopped').disabled=false;
  $('extendedCloudWarning').classList.toggle('hide',!cloud);
  $('timerHint').textContent=cloud?'HTTPS Cloud: 30 seconds to 120 minutes, or Until Stopped (experimental). A fresh callback is required at least every 90s.':'Home LAN: 30 seconds to 120 minutes, or Until Stopped.';
}

function clearRequestError(){stickyError='';$('requestError').classList.add('hide');$('requestError').textContent='';} 
async function api(path,data){const opts={headers:{'X-Edge-Key':key}};if(data!==undefined){opts.method='POST';opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(data)}const response=await fetch(path,opts);let result={};try{result=await response.json()}catch(e){}if(response.status===401){sessionStorage.removeItem('edgeKey');$('login').classList.remove('hide');throw Error('Invalid access key')}if(!response.ok||result.error)throw Error(result.error||'HTTP '+response.status);return result}
function duration(n){return String(Math.floor(n/60)).padStart(2,'0')+':'+String(n%60).padStart(2,'0')}
function display(s){
  // The public LAN profile has no cloud pairing or callback endpoints.
  if(s.profile === "lan") {
    $("pairingPanel").classList.add("hide");
    $("cloudStatus").closest(".cloud-detail").classList.add("hide");
    $("cloudApiDetail").classList.add("hide");
  } else {
    $("pairingPanel").classList.remove("hide");
    $("cloudStatus").closest(".cloud-detail").classList.remove("hide");
  }
  lastStatus=s;
  syncTimerRoute(s);
  // A normal cloud Stop is NOT a connection fault. Keep the server-side lock,
  // but ask for physical-off confirmation only when starting another session.
  // Never suppress a failed Stop, a pending recovery, or a connection fault.
  const routineCloudStop=s.cloudRoutineStopConfirmRequired===true&&
    s.faultLatched===true&&s.cloudRequiresPhysicalOff===true&&s.stopPending===false;
  routineConfirmRequired=!!routineCloudStop;
  if(!routineCloudStop)routineConfirmExpanded=false;
  const genuineFault=!!s.faultLatched&&!routineCloudStop;
  const visibleFault=s.faultLatched&&(!routineCloudStop||routineConfirmExpanded);
  $('safetyFault').classList.toggle('hide',!visibleFault);
  // A new real fault must be visible even when the user is far down the page.
  if(genuineFault&&!priorGenuineFault)requestAnimationFrame(()=>$('safetyFault').scrollIntoView({block:'center',behavior:'instant'}));
  priorGenuineFault=genuineFault;
  $('safetyFault').classList.toggle('routine-confirmation',!!routineCloudStop);
  $('safetyFault').setAttribute('role',routineCloudStop?'status':'alert');
  $('safetyTitle').textContent=routineCloudStop?'Before your next session':'CONNECTION FAULT — PHYSICAL MOTOR STATE UNKNOWN';
  $('safetyFaultText').textContent=routineCloudStop?
    'Cloud Stop was accepted by the server, but device delivery cannot be verified. Switch off your Edge 2 and confirm to unlock another session.':
    s.cloudRequiresPhysicalOff?'The cloud connection or Stop needs attention. Stop delivery is unverified. Physically switch off the Edge 2 before continuing.':
    s.stopPending?'Automatic Stop is pending on the original '+(s.faultRoute||'session')+' route. Physical Stop is unverified.':
    'Recovery Stop was accepted by the phone API, but physical stopping has not been independently verified.';
  $('ackFault').textContent=routineCloudStop?'Confirm power-off & unlock controls':'Acknowledge after checking physical device';
  if(!s.faultLatched)$('cloudOffConfirm').checked=false;if(s.faultLatched&&s.cloudRequiresPhysicalOff)$('acceptExtendedCloudRisk').checked=false;lastCloudOffRequired=!!s.cloudRequiresPhysicalOff;lastStopPending=!!s.stopPending;$('cloudOffLabel').classList.toggle('hide',!lastCloudOffRequired);$('ackFault').disabled=lastCloudOffRequired?!$('cloudOffConfirm').checked:!!s.stopPending;$('start').disabled=!!s.faultLatched&&!routineCloudStop;$('manual').disabled=!!s.faultLatched&&!routineCloudStop;$('test').disabled=!!s.faultLatched&&!routineCloudStop;lastRunning=!!s.running;updateStartButton();$('current').textContent=labels[s.mode]||s.mode;$('msg').textContent=stickyError||s.message||'Ready';$('pill').textContent=s.running?'Running':'Standby';$('dot').classList.toggle('live',s.running);$('stopDock').classList.toggle('hide',!s.running);let n=Math.max(0,s.secondsLeft||0);$('left').textContent=s.untilStopped?'∞':String(Math.floor(n/60)).padStart(2,'0')+':'+String(n%60).padStart(2,'0');$('timerLabel').textContent=s.untilStopped?'until you press Stop':'remaining';$('sessionProgress').style.width=(s.sessionProgress||0)+'%';$('bar1').style.width=(s.motor1||0)*5+'%';$('bar2').style.width=(s.motor2||0)*5+'%';
$('level1').textContent=(s.motor1||0)+' / 20';$('level2').textContent=(s.motor2||0)+' / 20';
$('battery').textContent=s.battery==null?'—':s.battery+'%'+(s.batteryIsStale?'*':'');$('batteryBar').style.width=s.battery==null?'0%':s.battery+'%';
$('batteryNote').textContent=(s.batterySource||'No report')+(s.batteryIsStale?' · last known, not live':' · last reported');
const home=s.connectionMode==='lan', cloud=s.connectionMode==='cloud', paired=s.cloudPairingConfirmed===true, ready=paired&&s.cloudExperimentalEnabled===true&&s.cloudCanStart===true, cachedRoutine=paired&&routineCloudStop, uncertain=true;
$('connection').textContent=home?(s.toyConnected===true?'Connected (LAN)':'LAN unavailable'):ready?'HTTPS paired (unverified)':cachedRoutine?'HTTPS pairing cached':cloud?(s.cloudLastErrorCode===507?'Cloud error 507':'Cloud offline'):'Not connected';
$('connection').className='stat-number small-number '+((home&&s.toyConnected===true)||ready?'online':cachedRoutine?'':'danger');
$('connectionNote').textContent=home?(s.toyConnected===true?'Home Wi-Fi Game Mode':s.lastDeviceError||'LAN unavailable'):(ready?'HTTPS callback cached; API/physical delivery not guaranteed':cachedRoutine?'Cloud Stop accepted; confirm device off before restarting':(s.cloudKeeperMessage||'Cloud connection unavailable'));
$('cloudDot').className='cloud-indicator bad';
$('cloudStatus').textContent=paired?'HTTPS pairing: cached, online unknown':'HTTPS pairing: '+(s.cloudKeeperState||'unavailable').replaceAll('_',' ');
$('cloudAge').textContent=s.cloudKeeperAgeSec==null?'':' · checked '+s.cloudKeeperAgeSec+'s ago';
function lastEvent(utc){if(!utc)return 'No recent device report';const t=Date.parse(utc), n=Date.now();if(!Number.isFinite(t))return 'Device report time unknown';const seconds=Math.max(0,Math.floor((n-t)/1000));return seconds<60?'Last device report '+seconds+'s ago':seconds<3600?'Last device report '+Math.floor(seconds/60)+'m ago':'Last device report '+new Date(t).toLocaleString()}
$('lastSeen').textContent=lastEvent(s.lastCloudDeviceEventUTC);
$('connectionWarning').classList.toggle('hide',!s.connectionWarning);
$('elapsed').textContent=duration(s.elapsedSeconds||0);$('commands').textContent=s.sessionCommands||0;
$('commandsNote').textContent=cloud?'Accepted by Lovense server; physical vibration unverified':'Commands sent in current session';
const cr=s.cloudLastCommand||{}, crLabel=cr.result==='api_accepted'?'Accepted by Lovense API':cr.result==='rejected'?'Rejected by Lovense API':cr.result==='transport_failed'?'Cloud transport failure':'No cloud commands recorded';
const crTime=cr.at_utc?new Date(cr.at_utc).toLocaleTimeString():'';
$('cloudApiDetail').classList.toggle('hide',!cloud);
$('cloudApiDetail').textContent='Cloud API: '+crLabel+(cr.action?' · '+cr.action:'')+(cr.code!=null?' · API code '+cr.code:'')+(crTime?' · '+crTime:'')+' · Accepted ≠ physical delivery.'+(s.cloudBlockedAfter507?' Cloud locked after 507 until a fresh device report.':'')+(s.cloudStartReason?' Cloud readiness: '+s.cloudStartReason:'');
const director=s.mode==='autonomous'&&s.running;
$('sceneName').textContent=director?(s.directorScene||'Preparing'):'Waiting to start';
$('directorPhase').textContent=director?(s.directorPhase||'Preparing'):'—';
const nextIntent=director?(s.directorIntent||'Choosing the next move'):'Ready for your next session';if($('intentLine').textContent!==nextIntent)$('intentLine').textContent=nextIntent;
$('sceneTime').textContent=director?(s.directorSceneSecondsLeft||0)+'s':'—';
$('decisionCount').textContent=director?(s.directorDecisions||0):'0';
$('energyVal').textContent=director?(s.directorEnergy||0)+'%':'—';
$('energyBar').style.width=director?(s.directorEnergy||0)+'%':'0%';
$('stageChip').textContent=director?'CHAPTER · '+(s.directorPhase||'Preparing'):(s.running?'PATTERN · '+(labels[s.mode]||s.mode):'Waiting for session');
$('sceneChip').textContent=director?'SCENE · '+(s.directorScene||'Preparing'):(s.running?'Running · '+(labels[s.mode]||s.mode):'Live scene · —');
$('directorInfo').textContent=director?'Local scene planner · '+(s.directorDecisions||0)+' decisions · '+(s.directorReprises||0)+' deliberate callbacks · '+(s.directorFlow||'balanced')+' flow. No sensory feedback or live human operator.':'A local scene planner, not a person or responsive AI. Every change stays within your maximum intensity, timer and Motor 2 contribution.';
$('updated').textContent=cloud?(ready?(uncertain?'HTTPS cloud device status unverified':'HTTPS cloud paired (unverified)'):'Cloud unavailable'):s.lastDeviceCheckSec==null?'Checking device…':'LAN checked '+s.lastDeviceCheckSec+'s ago';pairingProgress(s);}
function error(e){stickyError=e.message||String(e);$('msg').textContent=stickyError;$('requestError').textContent=stickyError;$('requestError').classList.remove('hide')}
async function run(path,body){if(pending)return;pending=true;try{const s=await api(path,body);clearRequestError();display(s)}catch(e){error(e)}finally{pending=false}}
function askRoutineConfirmation(){
 if(!routineConfirmRequired)return false;
 routineConfirmExpanded=true;
 if(lastStatus)display(lastStatus);
 $('safetyFault').scrollIntoView({block:'center',behavior:'instant'});
 return true;
}
$('start').onclick=()=>{if(askRoutineConfirmation())return;run(lastRunning?'/api/switch':'/api/start',settings())};
// STOP must never be blocked by a pending Start or other UI request.
const stopNow=async()=>{try{const s=await api('/api/stop',{});clearRequestError();display(s)}catch(e){error(e)}};
$('stop').onclick=stopNow; $('dockStop').onclick=stopNow;
$('manual').onclick=()=>{if(askRoutineConfirmation())return;run(lastRunning?'/api/switch':'/api/start',settings('manual'))};
$('test').onclick=()=>{if(askRoutineConfirmation())return;run('/api/test',{})};
$('cloudOffConfirm').addEventListener('change',()=>{$('ackFault').disabled=lastCloudOffRequired?!$('cloudOffConfirm').checked:lastStopPending});$('ackFault').onclick=()=>{const ok=lastCloudOffRequired&&$('cloudOffConfirm').checked;run('/api/ack-fault',{physicalOffConfirmed:ok});};
$('check').onclick=async()=>{try{const x=await api('/api/check');clearRequestError();display(x);$('msg').textContent=x.toyConnected?(x.connectionMode==='lan'?'Edge 2 connected via LAN':'HTTPS pairing cached; device connection unverified'):'Device not verified — check Lovense Remote and HTTPS pairing' }catch(e){error(e)}};
['m1','m2'].forEach(id=>$(id).addEventListener('input',()=>{if(!lastRunning)return;clearTimeout(sliderTimer);sliderTimer=setTimeout(()=>run('/api/switch',settings('manual')),330)}));
// Pairing QR is generated ONLY on explicit request, never by polling.
// Keep image private to the authenticated browser and clear on Hide/unlock change.
let pairingRequestTime=0, pairingWaiting=false;
$('pairQrButton').addEventListener('click',async()=>{
 if(lastRunning){$('pairQrMessage').textContent='Stop the session before requesting a QR.';return;}
 $('pairQrButton').disabled=true;
 $('pairQrMessage').textContent='Requesting a fresh QR from Lovense…';
 try{
  const d=await api('/api/cloud/pair-qr',{});
  if(!/^data:image\/(jpeg|png);base64,[A-Za-z0-9+/=]+$/.test(d.image||''))throw Error('Unexpected pairing image');
  $('pairQrImage').src=d.image;
  const validCode=typeof d.code==='string'&&/^[A-Za-z0-9]{4,32}$/.test(d.code);
  $('pairQrCode').value=validCode?d.code:'';
  $('pairQrCodeArea').classList.toggle('hide',!validCode);
  $('pairQrNoCode').style.display=validCode?'none':'block';
  $('pairQrContent').classList.remove('hide');$('pairQrHide').classList.remove('hide');
  $('pairQrExpires').textContent='Expires approximately '+new Date(d.expiresUtc).toLocaleTimeString()+' (Lovense: 4 hours).';
  $('pairQrMessage').textContent='Pairing details ready. Scan QR or enter the code in Lovense Remote, then wait for the authenticated callback.';
  pairingWaiting=true;pairingRequestTime=Date.parse(d.issuedUtc)||Date.now();
 }catch(e){$('pairQrMessage').textContent=e.message||String(e)}
 finally{$('pairQrButton').disabled=false;}
});
function hidePairingSecrets(){
 $('pairQrImage').removeAttribute('src');$('pairQrCode').value='';
 $('pairQrContent').classList.add('hide');$('pairQrHide').classList.add('hide');
 $('pairQrCodeArea').classList.add('hide');pairingWaiting=false;
}
$('pairQrHide').addEventListener('click',()=>{
 hidePairingSecrets();
 $('pairQrMessage').textContent='Pairing details hidden. Generate another only if you need to pair again.';
});
$('pairQrCopy').addEventListener('click',async()=>{
 const code=$('pairQrCode').value;
 if(!/^[A-Za-z0-9]{4,32}$/.test(code))return;
 try{
  if(typeof navigator!=='undefined'&&navigator.clipboard&&navigator.clipboard.writeText){
   await navigator.clipboard.writeText(code);
  }else{
   $('pairQrCode').select();
   if(!document.execCommand||!document.execCommand('copy'))throw Error('Manual copy required');
  }
  $('pairQrMessage').textContent='Code copied. Open Lovense Remote → Input QR Code Number.';
 }catch(e){$('pairQrCode').select();$('pairQrMessage').textContent='Select and copy the pairing code manually.';}
});
function pairingProgress(s){
 if(!pairingWaiting)return;
 const t=Date.parse(s.lastCloudDeviceEventUTC||'');
 if(Number.isFinite(t)&&t>=pairingRequestTime&&s.cloudPairingConfirmed===true){
  hidePairingSecrets();
  $('pairQrMessage').textContent='Pairing confirmed for one Edge 2. Current Bluetooth/cloud delivery is still not independently verified.';
 }
}
$('loginForm').addEventListener('submit',async e=>{e.preventDefault();key=$('key').value.trim();try{display(await api('/api/status'));sessionStorage.setItem('edgeKey',key);$('login').classList.add('hide');$('loginError').textContent=''}catch(e){$('loginError').textContent=e.message}});
async function poll(){if(!key||!$('login').classList.contains('hide'))return;try{display(await api('/api/status'))}catch(e){error(e)}}
setInterval(poll,1000);
if(key){api('/api/status').then(s=>{display(s);$('login').classList.add('hide')}).catch(()=>{sessionStorage.removeItem('edgeKey');$('login').classList.remove('hide')})}
})();
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = "EdgeLocal/1.0"
    def log_message(self, fmt, *args):
        # Avoid filling journals with 1-second polling requests.
        if args and str(args[0]).startswith('GET /api/status '):
            return
        print(f"[{self.log_date_time_string()}] {self.client_address[0]}: {fmt % args}", file=sys.stderr)

    def _reply(self, code, content, content_type):
        body = content.encode("utf-8") if isinstance(content, str) else content
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, data):
        self._reply(code, json.dumps(data), "application/json; charset=utf-8")

    def _authorized(self):
        return hmac.compare_digest(self.headers.get("X-Edge-Key", ""), self.server.key)

    def _needs_auth(self):
        if self._authorized():
            return False
        self._json(401, {"error": "Invalid access key"})
        return True

    def do_GET(self):
        if self.path == "/":
            self._reply(200, HTML, "text/html; charset=utf-8")
        elif self.path == "/favicon.ico":
            self._reply(200, b"", "image/x-icon")
        elif self.path in ("/api/status", "/api/check"):
            if self._needs_auth(): return
            if self.path == "/api/status":
                self._json(200, self.server.engine.status())
            else:
                try:
                    self._json(200, self.server.engine.refresh_toys())
                except RuntimeError as exc:
                    self._json(503, {"error": str(exc)})
        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path not in ("/api/start", "/api/switch", "/api/stop", "/api/test", "/api/ack-fault", "/api/cloud/pair-qr"):
            self._json(404, {"error": "Not found"}); return
        if self._needs_auth(): return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 2048: raise ValueError("Request too large")
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if self.path == "/api/cloud/pair-qr":
                if not isinstance(self.server.engine, HybridEngine):
                    self._json(404, {"error": "Cloud pairing unavailable in LAN profile"})
                    return
                if not isinstance(data, dict) or data:
                    raise ValueError("QR pairing takes no request parameters")
                result = self.server.pair_qr.generate(self.server.engine)
            elif self.path == "/api/stop":
                result = self.server.engine.stop()
            elif self.path == "/api/ack-fault":
                if not isinstance(data, dict):
                    raise ValueError('Invalid acknowledgement payload')
                if isinstance(self.server.engine, HybridEngine):
                    result = self.server.engine.acknowledge_fault(physical_off=data.get('physicalOffConfirmed') is True)
                else:
                    result = self.server.engine.acknowledge_fault()
            elif self.path == "/api/test":
                result = self.server.engine.test()
            elif self.path == "/api/switch":
                result = self.server.engine.switch_pattern(data)
            else:
                result = self.server.engine.start(data)
            self._json(200, result)
        except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self._json(503, {"error": str(exc)})


def access_key():
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if len(key) < 12:
            raise RuntimeError("Existing access key file seems invalid")
        KEY_FILE.chmod(0o600)
        return key
    key = secrets.token_urlsafe(18)
    fd = os.open(str(KEY_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key + "\n")
    return key


def build_engine(profile, phone, token="", uid="local-owner", simulate=False):
    """Select a tested profile without importing live credentials for LAN-only use."""
    if profile == "lan":
        return Engine(phone, simulate=simulate)
    if profile == "hybrid":
        return HybridEngine(phone, token=token, uid=uid, simulate=simulate)
    raise ValueError("Unknown PulseDirector profile")


def main():
    p = argparse.ArgumentParser(description="Free Lovense Edge 2 web dashboard")
    p.add_argument("--phone", default=DEFAULT_PHONE, help="Phone IP from Lovense Remote Game Mode; required for live LAN control")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--bind", default="127.0.0.1", help="Listening interface; loopback by default, specify trusted LAN IP explicitly")
    p.add_argument("--profile", choices=("lan", "hybrid"), default="hybrid",
                   help="lan disables cloud pairing/commands; hybrid enables optional HTTPS cloud")
    p.add_argument("--no-print-key", action="store_true", help="Do not print the access key (recommended with systemd)")
    p.add_argument("--uid", default="local-owner", help="Legacy identifier (ignored by HTTPS cloud transport)")
    p.add_argument("--simulate", action="store_true", help="Simulate device I/O for testing")
    args = p.parse_args()
    key = access_key()
    token = ""
    if args.profile == "hybrid" and not args.simulate and CLOUD_TOKEN_FILE.exists():
        if CLOUD_TOKEN_FILE.stat().st_mode & 0o077:
            raise RuntimeError(".edge_cloud_token must not be accessible by group or others; run chmod 600")
        token = CLOUD_TOKEN_FILE.read_text(encoding="utf-8").strip()
    engine = build_engine(args.profile, args.phone, token=token, uid=args.uid, simulate=args.simulate)
    try:
        http = ThreadingHTTPServer((args.bind, args.port), Handler)
    except OSError:
        engine.shutdown()
        raise
    http.engine, http.key = engine, key
    http.pair_qr = PairingQRManager()
    print("\n  EDGE 2 — HOME LAN + HTTPS CLOUD DASHBOARD\n")
    print(f"  Open:       http://{args.bind}:{args.port}")
    if not args.no_print_key:
        print(f"  Access key: {key}")
    else:
        print("  Access key: stored beside the dashboard script (not logged)")
    print(f"  Home phone: {args.phone}:20010")
    print(f"  Profile:    {args.profile}")
    print(f"  Cloud:      {'CONFIGURED' if token else 'not configured/disabled'}")
    print(f"  Mode:       {'SIMULATION (no toy control)' if args.simulate else 'LIVE (real device)'}")
    print("\n  Keep Lovense Remote connected. Game Mode is only needed for LAN. Press Ctrl+C to stop.\n", flush=True)

    def handle_signal(signum, frame):
        threading.Thread(target=http.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, handle_signal)
    try:
        http.serve_forever(poll_interval=.3)
    except KeyboardInterrupt:
        pass
    finally:
        http.server_close()
        engine.shutdown()
        print("Dashboard stopped; STOP sent if the phone was reachable.")


if __name__ == "__main__":
    main()
