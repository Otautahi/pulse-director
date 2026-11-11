# PulseDirector v4.6 — read-only diagnostics contract v1 (experimental)

This is an **opt-in, strictly read-only diagnostic interface** for the
PulseDirector v4.6 source candidate. It does not modify motor, session,
pairing, recovery or cloud behavior. **It is not enabled in the running
owner installation merely because this source exists on GitHub.**

## Transport and access

- **HTTP path:** `GET /api/diagnostics/v1`
- **Transport:** Unix-domain stream socket, **not a TCP port**.
- **Socket location:** chosen by the operator using `--diagnostics-socket ABSOLUTE_PATH`.
- **Default:** **disabled**, no socket and no additional server.
- **Access control:** socket file owned by the PulseDirector process user,
  `0600`, inside an existing same-user-owned `0700` directory.
- **Dashboard key:** **not required and never shared with monitoring clients**.
- **Monitoring client prerequisite:** the collector must be authorized to access
  the socket as its owner. Do not loosen filesystem permissions to grant
  access; use a reviewed separate access mechanism if the processes run
  under different users.
- **No public LAN endpoint:** requests to the ordinary dashboard
  `/api/diagnostics/v1` are not routed to this interface.
- **No control endpoint:** all non-GET methods return `405`, all other GET
  paths return `404`. A busy engine state lock returns a sanitized
  `503` without waiting indefinitely.
- **Performance:** pure in-memory snapshot, short timed lock acquisition,
  8 KiB maximum JSON response, no background polling, files, device I/O,
  cloud pairing helpers or credential reads.
- **Security:** never mount this socket on a public filesystem, share it
  with untrusted containers, forward it over a network, or expose it with
  an unauthenticated TCP proxy.

## Isolated simulation preview (does not touch your live dashboard)

On a **new source checkout, not over your existing Pi installation**, create
an owner-only directory. The paths below are examples only.

```bash
mkdir -p -m 700 "$HOME/.pulsedirector-diagnostics"
chmod 700 "$HOME/.pulsedirector-diagnostics"
cd /path/to/a/separate/pulse-director-checkout
python3 -m unittest discover -s tests -q
python3 edge_dashboard.py --profile lan --simulate --port 8876 \
  --diagnostics-socket "$HOME/.pulsedirector-diagnostics/pulsedirector.sock"
```

From another terminal **on the same Pi**, using the same Unix account:

```bash
curl --fail --silent --show-error \
  --unix-socket "$HOME/.pulsedirector-diagnostics/pulsedirector.sock" \
  http://localhost/api/diagnostics/v1
```

The simulator does not contact a real Edge 2. Stop it with Ctrl+C. On normal
shutdown the diagnostic socket is removed if still owned by that instance.
If a crash leaves a stale socket, **first confirm the old process is gone**;
do not blindly unlink a socket that may belong to an active instance.

Do not test a real device to check diagnostics. Do not run another live
controller against the same Edge 2.

## JSON contract

The response is a **strict allowlist**. A supported value is represented
as an object containing `value`, `supported`, `source` and `freshness`.
An unsupported field uses `value: null`, `supported: false`,
`source: "not_instrumented"`, `freshness: "unavailable"`, and `reason`.

```json
{
  "report": "PulseDirector diagnostics",
  "schema_version": 1,
  "collected_at_utc": "2026-11-11T08:00:00+00:00",
  "application": {
    "version_family": {"value":"v4.6","supported":true,"source":"running_code","freshness":"current"},
    "exact_release": {"value":null,"supported":false,"source":"not_instrumented","freshness":"unavailable","reason":"exact_installed_release_not_exposed"},
    "profile": {"value":"lan","supported":true,"source":"startup_configuration","freshness":"current"},
    "started_at_utc": {"value":"2026-11-11T07:55:00+00:00","supported":true,"source":"diagnostics_server_start","freshness":"current"},
    "uptime_seconds": {"value":300,"supported":true,"source":"monotonic_process_uptime","freshness":"current"},
    "last_classified_error": {"value":null,"supported":false,"source":"not_instrumented","freshness":"unavailable","reason":"no_timestamped_application_error_history"},
    "current_fault_category": {"value":null,"supported":true,"source":"active_fault_latch","freshness":"current"}
  },
  "connection": {
    "last_known_state": {"value":"reported_connected","supported":true,"source":"cached_phone_game_mode_telemetry","freshness":"fresh","age_seconds":5,"current_connection_verified":false},
    "transport": {"value":"lan","supported":true,"source":"cached_application_route","freshness":"current"},
    "failure_count": {"value":null,"supported":false,"source":"not_instrumented","freshness":"unavailable","reason":"connection_failure_counter_not_recorded"},
    "last_disconnection_at": {"value":null,"supported":false,"source":"not_instrumented","freshness":"unavailable","reason":"disconnect_timestamp_not_recorded"},
    "last_reconnection_at": {"value":null,"supported":false,"source":"not_instrumented","freshness":"unavailable","reason":"reconnect_timestamp_not_recorded"},
    "cached_error_category": {"value":null,"supported":false,"source":"not_instrumented","freshness":"unavailable","reason":"no_timestamped_connection_error_history"}
  },
  "session": {
    "last_outcome": {"value":null,"supported":false,"source":"not_instrumented","freshness":"unavailable","reason":"session_outcome_history_not_recorded"},
    "last_interruption_category": {"value":null,"supported":false,"source":"not_instrumented","freshness":"unavailable","reason":"session_interruption_history_not_recorded"}
  },
  "recovery": {
    "fault_latched": {"value":false,"supported":true,"source":"application_memory","freshness":"current"},
    "pending": {"value":false,"supported":true,"source":"application_memory","freshness":"current"},
    "last_attempt": {"value":null,"supported":false,"source":"not_instrumented","freshness":"unavailable","reason":"timestamped_recovery_attempt_not_recorded"},
    "last_outcome": {"value":null,"supported":false,"source":"not_instrumented","freshness":"unavailable","reason":"recovery_outcome_history_not_recorded"}
  },
  "stop": {
    "last_request_outcome": {"value":null,"supported":false,"source":"not_instrumented","freshness":"unavailable","reason":"timestamped_stop_outcome_not_recorded"},
    "cached_error_present": {"value":false,"supported":true,"source":"application_memory","freshness":"current"},
    "physical_motor_state": {"value":"unverified","supported":true,"source":"no_physical_motor_feedback","freshness":"unverifiable"}
  },
  "events": {
    "supported": false, "retention_seconds": 0, "max_items": 0,
    "items": [], "reason": "no_sanitized_event_history_in_current_engine"
  },
  "limitations": [
    "Cached phone reports are not a live physical device connection guarantee.",
    "Cloud pairing events are not connection heartbeats.",
    "A software or cloud Stop acknowledgement is not physical Stop proof.",
    "No historical counters or event timestamps are synthesized."
  ]
}
```

The example above is **illustrative**, not a record of any real toy or
production instance. Actual values come from the running process.

### Definitions and evidence

| Field | What it means | Important limit |
|---|---|---|
| `application.version_family` | Constant v4.6 code family | Not an exact installed git SHA/tag or owner's private production version |
| `application.started_at_utc` | Diagnostics server startup time | Only reports time since this optional server started |
| `application.uptime_seconds` | Monotonic time since optional diagnostics server started | Not OS/service uptime if diagnostic listener is restarted independently |
| `connection.last_known_state` | Cached phone Game Mode observation; aged by a monotonic timestamp | **Not** a verified live Bluetooth state; marks stale after 45 seconds |
| `connection.transport` | Cached route enumeration (`lan`, `cloud`, `simulation`, `unavailable`, `unknown`) | Cloud is never represented as verified live connection |
| `connection.cached_error_category` | Safe classification of last cached unstructured connection error | No reliable error timestamp, so freshness is `unverifiable` |
| `application.current_fault_category` | Allowlisted category of current latched fault, if any | No raw message or history |
| `recovery.fault_latched` | Current software latch | Never proves physical device status |
| `recovery.pending` | Current pending software recovery flag | Not evidence that Stop reached device |
| `stop.cached_error_present` | Whether application memory contains Stop failure text | Not a timestamped outcome of the most recent Stop |
| `stop.physical_motor_state` | Constant `unverified` | Software has no independent physical motor sensor |

The classifier only emits: `stop_delivery_failed`,
`cloud_pairing_unavailable`, `cloud_command_rejected`,
`phone_game_mode_unreachable`, `device_unsupported_or_ambiguous`,
`device_reported_disconnected`, `other_unclassified_error`.
Raw error strings, IPs, tokens, device names, IDs, settings, patterns,
intensities, motor commands and history are **never serialized**.

**Unsupported in v1:** timestamped application errors, failure counters,
disconnect/reconnect times, session outcomes, interruption history,
recovery attempt/outcome history, exact Stop result and sanitized event
history. These require future **separate reviewed instrumentation**;
Monitoring clients must show `unavailable` rather than guessing.

### Failure responses

- `200`: sanitized diagnostic snapshot.
- `404`: anything except the exact diagnostics GET path.
- `405`: any non-GET HTTP method.
- `503`: state lock timeout or an internal snapshot failure; a sanitized
  reason is returned. **Never treat this as a healthy state.**
- Socket connect/permission failure: listener unavailable, wrong Unix
  account or inaccessible path. Do not change dashboard permissions.

## Release, backup and rollback boundaries

This candidate is a **GitHub source branch** until explicitly staged and
tested on a designated test host. It does **not** update a private
`edge2-dashboard.service` automatically.

1. Keep the current private installation and systemd unit untouched.
2. Stage or clone the candidate into a **separate folder**, run all offline
   tests and use only `--simulate` for initial socket tests.
3. Confirm source files included in packaging: `pulsedirector_diagnostics.py`,
   `edge_dashboard.py`, Director/pairing helpers; `stage.sh` and Docker
   whitelist are updated accordingly.
4. Record the candidate commit SHA, preserve existing configuration and
   create a versioned backup/rollback snapshot **before any future deployment**.
5. Treat addition of `--diagnostics-socket` to the production systemd
   `ExecStart` as a separate opt-in change, never implicit in a
   documentation or public GitHub update.
6. Rollback means restoring the previous code and previous systemd command,
   then confirming the normal dashboard and service work. Do not disturb other applications, services or host configuration.

## Handoff to a monitoring client

**Do not configure monitoring clients until the actual local installation is verified.**
After a separate deployment, record:

- Actual installed PulseDirector version/commit.
- Explicit owner-only socket pathname, expected Unix user and permissions.
- Successful `GET /api/diagnostics/v1` response schema v1.
- Polling interval and freshness handling (e.g. every 60 seconds) to avoid
  excessive resource use on low-power hardware.
- Per-field `supported`, `source`, `freshness`, `reason`, plus captured
  UTC time; preserve `503` and socket failures as unavailable.
- Never copy raw socket data to public logs or assume physical Stop.

Monitoring clients should consume this API read-only, preserve their own
privacy and export policies, and avoid probing control routes.
