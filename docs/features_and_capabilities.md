# TheKilnGod Feature and Capability Inventory

## Purpose

This document inventories what the current program already does so you can decide how much to rewrite, and in what direction.

Project goal today: turn a Raspberry Pi (and other Blinka-supported boards) into a kiln controller with web control, safety behavior, profile management, and live telemetry.

**Verification Status**: Validated against codebase on 2026-03-01.

## High-Level System Summary

- **Runtime/controller process**: `thekilngod server` (Bottle web framework + Gevent WebSocket)
- **Core kiln logic and PID loop**: `src/thekilngod/oven.py`
- **Configuration**: `config.py` with optional local `secrets.py` overrides
- **Browser UI**: `public/index.html` + `public/assets/js/picoreflow.js`
- **Advanced state dashboard**: `public/state.html` + `public/assets/js/state.js`
- **Persistent profiles**: `storage/profiles/*.json`
- **Local OLED display**: `src/thekilngod/display.py` (driver) + `src/thekilngod/display_updater.py` (integration thread)
- **Home Assistant integration**: `src/thekilngod/homeassistant_mqtt.py`
- **External watcher/alerts**: `thekilngod watcher` (Standalone script, Slack webhook)
- **Data capture and tuning**: `thekilngod logger`, `thekilngod tuner`

## Functional Capabilities

### 1) Kiln Run Control

- Start a profile by name via HTTP API (`POST /api`, cmd `run`)
- Start from a specific minute offset (`startat`) for restart/skip scenarios
- Stop active run (`stop`)
- Pause and resume (`pause`, `resume`)
- Control channel over WebSocket (`/control`) for RUN/STOP commands
- Maintains primary run states:
  - `IDLE`
  - `RUNNING`
  - `PAUSED`

### 2) Profile/Schedule Management

- Profile storage as JSON files on disk in `storage/profiles`
- Load/list profiles over WebSocket storage channel (`/storage`, `GET`)
- Create/update profiles (`PUT`)
- Delete profiles (`DELETE`)
- Browser-based profile editor supports:
  - Adding/removing profile points
  - Editing target time and target temperature points
  - Visual graph editing (draggable points via Flot)
  - Schedule table editing
- Unit normalization:
  - Profiles are stored in Celsius (`temp_units: c`)
  - Runtime can convert to Fahrenheit for display if configured

### 3) Temperature Measurement

- Supports Adafruit MAX31855 and MAX31856 thermocouple boards via `src/thekilngod/oven.py`
- Thermocouple type support through MAX31856 (configurable in `config.py`):
  - B, E, J, K, N, R, S, T
- Hardware SPI and software SPI are supported (auto-selected by config)
- Temperature smoothing via median of sampled values (`TempTracker`)
- Configurable sampling window (`temperature_average_samples`)
- Configurable thermocouple offset calibration

### 4) Heat Output Control

- GPIO-based relay control (SSR expected) via `digitalio`
- Inverted/non-inverted output control via config (`gpio_heat_invert`)
- Time-proportional control in each cycle (`sensor_time_wait`)
- `heat_on` and `heat_off` durations computed per control cycle in `heat_then_cool`

### 5) PID and Thermal Control Behavior

- PID control with configurable `kp`, `ki`, `kd`
- PID stats exposed to UI and logging
- Integral windup protection by behavior:
  - Outside control window (`pid_control_window`), effectively hard heat/cool behavior
  - Inside control window, PID modulation
- Optional kiln catch-up mode:
  - If kiln is too cold/hot relative to target window, schedule time is shifted until kiln catches up
- Catch-up supervisor (shadow mode):
  - Computes multi-window lag/rise/duty trend metrics during runs
  - Produces `catchup_shadow_*` telemetry fields for diagnostics
  - Writes JSON-lines decisions to `storage/logs/catchup-shadow.jsonl`
  - Supports transient-drop holdoff to avoid overreacting to short disturbances (for example door-open events)
  - Default `shadow` mode does not change heater control or abort runs
- Low-temperature throttling options (`throttle_below_temp`, `throttle_percent`)
- Real-time computed heating rate (`degrees/hour`)

### 6) Start-Seek and Restart Behavior

- `seek_start` support:
  - If current kiln temp is already above first target point, system can seek forward in schedule to nearest matching temperature
- Automatic restart support after outages:
  - Periodic state snapshots to disk (`state.json`)
  - On process reboot, resumes prior run if state file is fresh and last state was `RUNNING`
  - Restart window is configurable in minutes (`automatic_restart_window`)

### 7) Safety and Fault Handling

- Emergency shutoff if temperature exceeds configured limit (`emergency_shutoff_temp`)
- Thermocouple health tracking:
  - Sliding-window error percentage (`ThermocoupleTracker`)
  - Abort if error rate crosses threshold (unless configured to ignore)
- Power/current anomaly detection (optional power sensor):
  - warns when heater is commanded but current stays below threshold for a sustained window
  - warns when power sensor feed is stale
- Mapped thermocouple fault classes (open circuit, short, voltage/range faults, etc.)
- Configurable ignore flags for specific fault classes (allows continuing run in known noisy environments)

### 8) Real-Time Monitoring and Telemetry

- WebSocket status stream (`/status`) with frequent state updates
- Backlog support for newly connected clients
- Live state includes:
  - Temperature, Target temperature
  - Runtime and total time
  - Heat output status
  - Profile name
  - PID stats (P, I, D components)
  - Catch-up status
  - Optional line voltage/current/power telemetry
  - Running cost estimate

### 9) Cost and Runtime Metrics

- Cost model based on configured kWh rate and element kW draw
- Cost estimated during runtime and displayed in UI
- Pre-run UI estimates job time and energy/cost summary

### 10) Local UI Features (Browser)

- Legacy but functional web interface (jQuery + Bootstrap + Flot/Plotly) for:
  - Selecting profiles
  - Starting/stopping runs
  - Editing schedules
  - Live graphing profile vs. measured temperature
  - Progress bar and status indicators
- Separate state dashboard (`/state`) for deeper PID diagnostics:
  - Error trend
  - Heat percentage
  - P/I/D component charts
  - Table export to CSV

### 11) Local Display Hardware Support

- Optional SSD1309 OLED support over I2C via `luma.oled`
- Local display can show:
  - State, Profile name
  - Current and target temperature
  - Runtime/remaining time, Heating rate
- Includes icon loading from `.hex` bitmap files in `images/hex` (e.g., flame, clock)

### 12) Home Assistant / MQTT Integration

- Optional MQTT publishing thread (`src/thekilngod/homeassistant_mqtt.py`)
- Configurable broker, credentials, topic prefix, client ID
- Publishes sensors for: temperature, target, status, heat (binary), time remaining, profile name, runtime, heat rate.

### 13) External Tooling and Operations

- `thekilngod logger`:
  - Connects to status WebSocket
  - Logs profile and PID stats to CSV
- `thekilngod tuner`:
  - Records heat-up/cool-down response
  - Computes PID parameters using Ziegler-Nichols-style method
- `thekilngod watcher`:
  - Polls `/api/stats`
  - Detects repeated failures or excessive error
  - Sends Slack webhook alerts
- System service files exist under `lib/init` (`kiln-controller.service`, `smoker.service`) for boot-time daemon startup

### 14) Simulation Support

- Full simulated oven mode (`simulate = True` in `config.py`)
- Simulated thermal model for software-only testing and UI exploration
- Supports accelerated time factors for faster simulation runs (`sim_speedup_factor`)

## Non-Functional Characteristics

### Runtime/Platform

- Primary runtime is Python on Linux (Raspberry Pi OS common path)
- Uses thread-based concurrency for:
  - Oven control loop
  - Thermocouple reader
  - Web server/websocket handling
  - Display updater
  - MQTT publisher

### Persistence

- File-based persistence only (profiles + restart state file)
- No relational DB dependency

### Deployment

- Simple single-host deployment model
- Designed to run on the kiln controller itself and serve UI over LAN

## Current Strengths to Preserve

- Proven real-world behavior on low-power hardware (Pi 3)
- Clear safety primitives already implemented
- Strong practical operational features:
  - auto-restart
  - catch-up
  - seek-start
  - live telemetry
- No heavy infrastructure requirements
- Simulation mode is valuable for testing rewrites

## Current Constraints / Technical Debt

- Frontend stack is older (jQuery + Bootstrap + Flot/Plotly mix)
- API design is command-style and mixed between HTTP and WebSocket conventions
- Minimal auth/security for network endpoints (LAN-trust assumption)
- Concurrency model is thread-heavy with shared mutable state
- Limited automated integration testing coverage for full run lifecycle
- Some docs/scripts indicate legacy evolution and mixed-generation code paths

## Rewrite Direction Options

### Option A: Frontend-Only Modernization (Lowest risk)

Keep Python control backend and rewrite UI only.

- Build a new responsive web UI (mobile-first)
- Keep existing API/WebSocket contracts initially
- Add better charts, run timeline, alerts UX, profile editor UX
- Fastest path to “phone app experience” without touching kiln control safety logic

Best when:
- You trust current control/safety behavior
- You mainly want usability/graphics/mobile improvements

### Option B: API + Frontend Modernization (Balanced)

Keep control loop, but formalize a cleaner backend interface.

- Introduce versioned REST + WebSocket event schema
- Keep old endpoints during transition
- Build modern UI or mobile app on stable API
- Add authentication and role model (view-only vs control)

Best when:
- You want both better UX and cleaner long-term maintainability
- You may add multiple clients (phone app + web + HA)

### Option C: Full Rewrite (Highest risk)

Rebuild backend control and UI from scratch.

- Enables deep architecture cleanup
- High validation burden because kiln control is safety-critical
- Requires careful simulation/hardware regression testing before production use

Best when:
- Core control logic is no longer trusted or extensible
- You can invest in formal test harnesses and staged commissioning

## Recommended Practical Path

Given your note that the system works well on a Pi 3, a phased rewrite is likely the safest:

1. Preserve control core first (`src/thekilngod/oven.py` behavior).
2. Add a clean, documented API layer around existing runtime.
3. Build new mobile-friendly UI (PWA first), then decide if native app is still needed.
4. Only rewrite control core after parity tests exist and safety behavior is captured.

## Phone App Direction (Without Immediate Full Rewrite)

- Step 1: Create a mobile-first web app (PWA) against existing/new API
  - installable on iOS/Android home screen
  - push-style notifications via backend hooks
- Step 2: If needed, wrap with Capacitor/React Native/Flutter later
- Step 3: Keep kiln-side controller simple and deterministic; keep app side mostly presentational + command/control

## Suggested Rewrite Boundaries

Good candidates to rewrite early:

- `public/` frontend (UI/UX refresh, responsive design, clearer workflow)
- API contract layer (typed payloads, explicit error handling)
- Auth and remote access hardening

Good candidates to keep initially:

- PID loop and control timing behavior
- Thermocouple read/error handling
- Automatic restart safety behavior
- Profile file format (at least until migration tooling exists)

## Capability Gaps You Could Add Next

- Phone notifications without Slack dependency (Push/SMS/Signal)
- Better fault diagnostics and guided recovery actions
- Profile versioning/history with rollback
- Multi-kiln support in one UI
- User accounts and audit log for run commands
- Better graphics:
  - richer timeline views
  - comparative run overlays
  - annotated events (pauses, catch-up, faults, restarts)
- Optional cloud relay for remote access without exposing local network ports

## Decision Checklist Before Rewriting

- Which failures are unacceptable (safety, overfire, silent crash, stale UI)?
- Do you need offline/local-only operation as a hard requirement?
- Is remote control required, or monitoring-only from phone?
- Do you need multi-user access control?
- Is profile compatibility with existing JSON files mandatory?
- Are you willing to run staged hardware validation before production firings?

## Bottom Line

You already have a capable kiln control platform, not just a prototype. The lowest-risk, highest-value path is usually:

- keep control logic,
- modernize API + UI,
- ship mobile-friendly experience first,
- then consider deeper backend rewrite only where current limits are proven.
