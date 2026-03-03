# TheKilnGod vs. The Original Bruce Project

## Overview

`TheKilnGod` is a substantial evolution of the original Bruce-style kiln-controller lineage (historically tied to the apollo-ng picoReflow project). While the original project provided a solid foundation for local-network, PID-driven kiln control, `TheKilnGod` introduces a modernized architecture, enhanced safety mechanisms, broader hardware support, and a completely rebuilt user interface.

This document outlines the practical differences and key improvements that make `TheKilnGod` the recommended choice for new and upgrading users.

## Key Advantages of TheKilnGod

### 1. Advanced Safety and Control Logic
Safety and reliability are critical when operating a kiln. `TheKilnGod` introduces several advanced control features not present in the original baseline:
- **Emergency Safeguards:** Automatic shutoffs for extreme temperatures and thermocouple error-rate tracking with emergency abort paths.
- **Smart Firing Resumption:** Automatic restart capabilities from the `state.json` window in case of power loss or interruption.
- **Dynamic Profile Execution:** Features like `seek_start` (starting later in a profile based on current kiln temperature) and time-shift catch-up logic when the kiln lags or leads the target schedule.
- **Hardware Protection:** A minimum on-time guard (`min_on_time`) reduces short-cycle relay chatter, extending the lifespan of solid-state relays (SSRs).

### 2. Expanded Hardware Compatibility
While the original project was heavily tied to specific Raspberry Pi GPIO patterns, `TheKilnGod` utilizes a Blinka-oriented design, opening up support for a wider variety of single-board computers and microcontrollers.
- **Thermocouple Support:** Out-of-the-box support for both MAX31855 and MAX31856 amplifiers, covering a broad range of thermocouple types (B, E, J, K, N, R, S, T).
- **Flexible SPI:** Supports both hardware and software SPI paths.
- **Local Peripherals:** Optional support for local OLED displays (SSD1309 over I2C) for at-a-glance status, and passive piezo buzzers for state, error, and completion alerts.

### 3. Modernized UI and User Experience
`TheKilnGod` maintains the familiar legacy web UI but significantly improves it, while also introducing a completely new modern dashboard.
- **Enhanced Legacy UI:** Includes better profile selection feedback, schedule previews, and a new schedule builder workflow for target/ramp/hold generation.
- **New React Dashboard (`ui-v2`):** A modern, Vite-powered React interface featuring health trend visualizations, event timelines, run summary views, and an intuitive schedule builder.

### 4. Rich Telemetry and Run Analysis
Understanding how your kiln performs over time is essential for maintenance and tuning. `TheKilnGod` tracks and persists detailed run health data:
- **Metrics Tracking:** Logs rolling error stats, relay duty/switch rates, temperature overshoot, and the percentage of time spent within 5 degrees of the target.
- **Historical Analysis:** Persists data to `storage/logs/run-health-history.jsonl` and includes tools (`thekilngod run-health`) for analyzing long-term kiln performance and identifying degrading hardware.
- **Audit Logging:** A dedicated `storage/logs/command-audit.log` ensures all control and storage commands are traceable.

### 5. Security and Integrations
`TheKilnGod` makes it easier to securely integrate your kiln into a modern smart home or maker environment.
- **API Security:** Introduces an optional token-based security model (`api_control_token` and `api_monitor_token`) to secure HTTP and WebSocket endpoints against unauthorized access on your local network.
- **Home Automation:** Native Home Assistant integration via MQTT (`src/thekilngod/homeassistant_mqtt.py`).
- **Notifications:** A built-in notification framework (`src/thekilngod/notifications.py`) optimized for services like `ntfy`.

### 6. Architectural Improvements
Under the hood, the backend was heavily rewritten (circa 2023) to improve maintainability and performance.
- Clear separation of concerns between web/API orchestration (`thekilngod server`), the PID control loop (`src/thekilngod/oven.py`), and pluggable peripherals.
- Updated service and boot workflows with path- and user-aware startup scripts for easier deployment.

## What Stays the Same?

If you are migrating from the original Bruce project, the core workflow remains familiar:
- Profile-based firing schedules.
- Browser-based operation and monitoring over a local network.
- The fundamental PID-driven control loop concept.

## Migration Checklist

If you are upgrading from the original Bruce baseline to `TheKilnGod`, verify the following during setup:
1. **Hardware Configuration:** Check GPIO pin mapping, output inversion, and SPI/thermocouple settings in `config.py`.
2. **System Services:** Update service paths, user permissions, and startup scripts to match the new repository layout.
3. **Security:** Consider enabling API tokens for monitor/control endpoints.
4. **Integrations:** Configure any new optional integrations (MQTT, notifications, OLED, buzzer).
5. **UI Access:** 
   - Legacy UI: Available at `/picoreflow/index.html`
   - Modern UI: Available at `/v2` (requires building `ui-v2` into `public/v2`).

---
*For more detailed information on specific features, refer to `docs/features_and_capabilities.md` and `docs/run_health.md`.*
