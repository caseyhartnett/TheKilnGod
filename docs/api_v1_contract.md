# API v1 Contract (Current Controller)

This document defines the current API/UI contract used by the legacy frontend and `ui-v2`.

Base URL examples assume default port `8081`.

## HTTP Endpoints

## `GET /ui-auth/status`

Returns the current lightweight `ui-v2` password-gate state.

Example response:

```json
{
  "success": true,
  "enabled": true,
  "unlocked": false
}
```

Notes:

- `enabled` depends on whether `KILN_UI_PASSWORD` is set in the server environment.
- `unlocked` is tracked with a browser-session cookie.

## `POST /ui-auth/unlock`

Unlock the `ui-v2` session when `KILN_UI_PASSWORD` is enabled.

Body:

```json
{
  "password": "your_ui_password"
}
```

Responses:

- success: `200`
- incorrect password: `401`
- invalid body: `400`

## `POST /ui-auth/lock`

Clears the current `ui-v2` unlock session cookie.

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
    "sensor_error_rate_5m": 0.0,
    "power_sensor_available": true,
    "power_sensor_ok": true,
    "power_sensor_stale_5m": 0.0,
    "power_sensor_error_rate_5m": 0.0,
    "line_voltage_now": 240.1,
    "line_current_now": 18.2,
    "line_power_now": 4370.2,
    "line_energy_wh_now": 12845.0,
    "line_voltage_avg_5m": 239.8,
    "line_current_avg_5m": 17.9,
    "line_power_avg_5m": 4290.4,
    "line_energy_wh_last_5m": 12845.0,
    "no_current_when_heating_pct_run": 0.0,
    "catchup_supervisor_enabled": true,
    "catchup_supervisor_mode": "shadow",
    "catchup_shadow_state": "normal",
    "catchup_shadow_avg_error_confidence": 8.2,
    "catchup_shadow_rise_rate_trend_deg_per_hour": 112.5,
    "catchup_shadow_duty_cycle_confidence_pct": 64.0,
    "catchup_shadow_lagging_seconds": 0.0,
    "catchup_shadow_cusum_deg_seconds": 0.0,
    "catchup_shadow_holdoff_active": false
  }
}
```

Catch-up shadow telemetry fields are additive and informational when
`catchup_supervisor_mode` is `shadow`. They do not imply automatic run abort.

Power/current telemetry fields are additive and are only populated when the
optional power sensor is enabled and healthy.

## `POST /api`

Command-style control endpoint.

Common request/response:

- Request body: JSON object with `cmd`
- Success response: `{ "success": true }`
- Validation/auth error response: `{ "success": false, "error": "..." }`

Validation behavior:

- Missing or non-object JSON body: `400`
- Missing `cmd`: `400`
- Unknown `cmd`: `400`
- Unauthorized request: `401`

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

Plain HTTP requests to websocket-only endpoints return `400`.

## Runtime Issue Events

`issue_detected` notifications may include:

- `heater_commanded_no_current`: heater was on while measured current remained below threshold
- `power_sensor_stale`: power sensor has not provided fresh data within alert window
- `catchup_shadow_would_extend`: shadow evaluator indicates lagging-but-rising condition
- `catchup_shadow_would_abort`: shadow evaluator indicates sustained inability to catch up

## `/storage`

Profile management channel.

- Send `"GET"` string to retrieve all profiles.
- Send JSON command object for mutation:
  - `{ "cmd": "PUT", "profile": { ... }, "force": false }`
  - `{ "cmd": "DELETE", "profile": { ... } }`

Mutation notes:

- Profile names are validated server-side and must stay within the configured profile directory.
- `PUT` returns `resp: "FAIL"` with `error: "Profile exists"` when a profile already exists and `force` is not true.
- On successful `PUT`, the server sends the command response followed by the refreshed profile list.

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
- `ui-v2` stores saved tokens in browser `sessionStorage` by default.
- Command/storage actions are audit-logged as JSON lines when `command_audit_enabled` is true.
