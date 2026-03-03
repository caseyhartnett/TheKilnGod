# API v1 Contract (Current Controller)

This document defines the current API/UI contract used by the legacy frontend and `ui-v2`.

Base URL examples assume default port `8081`.

## HTTP Endpoints

## `GET /api/stats`

Returns current PID stats and telemetry.

Example response shape:

```json
{
  "time": 1710000000,
  "timeDelta": 2.0,
  "setpoint": 1234.5,
  "ispoint": 1229.1,
  "err": 5.4,
  "errDelta": -0.1,
  "p": 54.0,
  "i": 123.0,
  "d": -22.0,
  "kp": 10,
  "ki": 80,
  "kd": 220.8,
  "pid": 31.2,
  "out": 0.31,
  "telemetry": {
    "window_seconds": 300,
    "error_now": 5.4,
    "error_avg_1m": 4.8,
    "error_avg_5m": 5.1,
    "error_abs_avg_5m": 6.2,
    "within_5deg_pct_5m": 71.2,
    "within_5deg_pct_run": 65.7,
    "switches_5m": 28,
    "switches_per_hour_run": 102.3,
    "duty_cycle_5m": 42.0,
    "overshoot_max_run": 9.5,
    "time_catching_up_pct_run": 3.4,
    "sensor_error_rate_5m": 0.0
  }
}
```

## `POST /api`

Command-style control endpoint.

Common request/response:

- Request body: JSON object with `cmd`
- Success response: `{ "success": true }`
- Error response for missing profile on run: `{ "success": false, "error": "..." }`

### Optional monitor/control auth

The API supports two optional tokens:

- `api_monitor_token`
- `api_control_token`

Tokens can be passed with:

- Header: `X-API-Token: <token>`
- Query parameter: `?token=<token>` (required for browser websockets)

Behavior:

- If neither token is set: open access (legacy behavior).
- If only `api_control_token` is set:
  - monitor endpoints require control token
  - control endpoints require control token
- If only `api_monitor_token` is set:
  - monitor endpoints require monitor token
  - control endpoints require monitor token
- If both are set:
  - monitor endpoints accept monitor token or control token
  - control endpoints require control token

Unauthorized command response:

```json
{ "success": false, "error": "unauthorized" }
```

### Commands

### `cmd: "run"`

Body:

```json
{
  "cmd": "run",
  "profile": "cone-6-long-glaze",
  "startat": 0
}
```

Notes:

- `profile` required.
- `startat` optional, minutes offset.

### `cmd: "pause"`

Body:

```json
{ "cmd": "pause" }
```

### `cmd: "resume"`

Body:

```json
{ "cmd": "resume" }
```

### `cmd: "stop"`

Body:

```json
{ "cmd": "stop" }
```

### `cmd: "stats"`

Body:

```json
{ "cmd": "stats" }
```

Returns same payload shape as `GET /api/stats`.

### `cmd: "memo"`

Body:

```json
{ "cmd": "memo", "memo": "operator note" }
```

Currently only logged server-side.

## Run Health API

## `GET /api/run-health`

Returns historical per-run health summaries.

Query params:

- `limit` (default 100, max 5000)
- `include_excluded` (`0` or `1`)

Auth role: monitor.

Example response:

```json
{
  "success": true,
  "rows": [],
  "exclusions": [],
  "returned": 0,
  "limit": 100
}
```

## `POST /api/run-health/exclusions`

Set or clear exclusion flag on a specific run.

Body:

```json
{
  "run_id": "uuid-string",
  "excluded": true
}
```

Auth role: control.

## WebSocket Endpoints

## `/status`

Push stream of oven state snapshots, including:

- `temperature`
- `target`
- `state` (`IDLE`, `RUNNING`, `PAUSED`)
- `heat`
- `runtime`, `totaltime`
- `pidstats`
- `catching_up`
- `telemetry`

Also sends a backlog envelope for new observers:

```json
{
  "type": "backlog",
  "profile": { "name": "...", "data": [[0, 20], [600, 200]], "type": "profile" },
  "log": []
}
```

Auth role: monitor.

## `/storage`

Profile management channel.

- Send `"GET"` string to retrieve all profiles.
- Send JSON command object for mutation:
  - `{ "cmd": "PUT", "profile": { ... } }`
  - `{ "cmd": "DELETE", "profile": { ... } }`

Auth role:

- monitor for websocket connection and `GET`
- control for `PUT` / `DELETE`

## `/config`

Returns config subset:

```json
{
  "temp_scale": "f",
  "time_scale_slope": "h",
  "time_scale_profile": "m",
  "kwh_rate": 0.14,
  "currency_type": "$"
}
```

Auth role: monitor.

## Compatibility Notes

- Legacy UI and `ui-v2` both rely on `/status`.
- New telemetry fields are additive and backward-compatible.
- Existing command semantics are preserved.
- If auth tokens are enabled, legacy UI pages do not automatically send them.
- Command/storage actions are audit-logged as JSON lines when `command_audit_enabled` is true.
