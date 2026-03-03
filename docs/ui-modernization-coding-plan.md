# UI Modernization Coding Plan

## Goal

Modernize the kiln UI with minimal risk by preserving current kiln-control behavior while adding clearer telemetry, mobile usability, and actionable statistics.

Primary focus:

- Better visibility into small control error
- A high-resolution “last 5 minutes” view showing error and relay on/off cycling
- Additional statistics including switch behavior and accuracy within 5 degrees

## Recommended Technical Direction

- Framework: React + TypeScript
- Tooling: Vite
- Approach: Build new UI in parallel (`ui-v2/`) while keeping current backend and legacy UI operational

Why:

- Lowest risk to kiln-control safety logic
- Fast iteration on UX and charts
- Good path to future phone/PWA experience

## Phase Plan

## Phase 1: Metric Definitions and Contract (1 day)

### Deliverables

- Define telemetry metric names, units, and formulas
- Confirm temperature tolerance behavior (`±5°F` or `±5°C` based on config)
- Define “relay switch” event consistently

### Metric Definitions (v1)

- `error_now`: `target - temperature`
- `error_avg_1m`: mean error over last 1 minute
- `error_avg_5m`: mean error over last 5 minutes
- `error_abs_avg_5m` (MAE): mean absolute error over last 5 minutes
- `within_5deg_pct_5m`: percent of last-5-min samples where `abs(error) <= 5`
- `within_5deg_pct_run`: percent of full-run samples where `abs(error) <= 5`
- `switches_5m`: count of heat output state transitions in last 5 minutes
- `switches_per_hour_run`: normalized switching rate over run
- `duty_cycle_5m`: percent time heat output is active in last 5 minutes
- `overshoot_max_run`: max observed `(temperature - target)` when positive
- `time_catching_up_pct_run`: percent run time spent in catch-up mode
- `sensor_error_rate_5m`: thermocouple read error percent in last 5 minutes

## Phase 2: Backend Telemetry Expansion (2-3 days)

### Files

- `lib/oven.py`
- `kiln-controller.py`

### Tasks

1. Add rolling telemetry buffers (deque) in oven state:
- timestamps
- temperature
- target
- error
- heat state
- switch events
2. Compute last-5-min and run-level aggregates.
3. Add telemetry object to `get_state()` output.
4. Ensure `/api/stats` includes key metrics.
5. Preserve backward compatibility for existing UI and scripts.

### Notes

- Switch count must increment only when heat state changes (`0->1` or `1->0`).
- Keep calculations lightweight to avoid affecting control loop timing.

## Phase 3: Quick UX Upgrade in Existing State Dashboard (1-2 days)

### Files

- `public/state.html`
- `public/assets/js/state.js`

### Tasks

1. Add a compact “Last 5 Minutes” panel:
- Error graph (high-resolution short window)
- Heat on/off step graph aligned to same time axis
2. Add stat cards:
- MAE (5m)
- `% within ±5°` (5m + run)
- `switches_5m`
- `switches_per_hour_run`
3. Add stale-data indicator if websocket updates stall.

### Acceptance

- User can visually identify small oscillations and switching behavior quickly.

## Phase 4: New UI (React + Vite) Foundation (4-6 days)

### New Directory

- `ui-v2/`

### Tasks

1. Bootstrap React+TS+Vite app.
2. Add websocket client with reconnect and heartbeat/stale handling.
3. Implement mobile-first live dashboard:
- current temp/target/state
- mini last-5-min charts (error + on/off)
- key stat cards
4. Add run control panel with safe confirmations.
5. Add read-only profiles page first; editing later.

## Phase 5: Validation and Safety Regression (2 days)

### Tasks

1. Verify telemetry correctness in simulation and live mode.
2. Compare legacy vs new values for overlapping fields.
3. Add unit tests for metric calculations:
- rolling-window averages
- `within_5deg` percentages
- switch counting
4. Confirm no control-loop degradation on Pi hardware.

### Performance Gate

- No observable increase in missed/late control cycles.
- CPU/memory overhead acceptable on Pi target hardware.

## Implementation Checklist

- [ ] Define and document metric formulas in code comments and docs
- [ ] Add rolling telemetry buffers in backend
- [ ] Expose telemetry in websocket state payload
- [ ] Expose telemetry in `/api/stats`
- [ ] Update legacy state dashboard with 5-minute graphs
- [ ] Add relay switching and accuracy stat cards
- [ ] Add stale-data warning state
- [ ] Scaffold `ui-v2` React+TS+Vite app
- [ ] Build responsive dashboard in `ui-v2`
- [ ] Add run controls with explicit confirmations
- [ ] Add tests for telemetry computations
- [ ] Validate on simulation + real hardware

## Suggested Future Metrics (Post-v1)

- `max_consecutive_out_of_tolerance_sec`
- `time_above_target_10deg_sec`
- `time_below_target_10deg_sec`
- `predicted_finish_time`
- `fault_events_count_run`

## Definition Clarifications

- “Within 5 degree accuracy” should be interpreted relative to current `config.temp_scale`.
- Metrics should exclude `IDLE` state unless explicitly marked as full-session values.

## Rollout Strategy

1. Ship backend telemetry first (no UI dependency).
2. Enable legacy dashboard enhancements.
3. Introduce `ui-v2` in parallel path.
4. Keep legacy UI as fallback through several firings.
5. Cut over when stable and trusted.

