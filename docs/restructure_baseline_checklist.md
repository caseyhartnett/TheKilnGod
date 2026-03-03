# Restructure Baseline Checklist

Use this checklist before and after restructuring to verify no functional behavior changed.

- Startup flow: `./thekilngod server` initializes and binds expected port.
- PID control loop: schedule run, pause, resume, and stop behavior unchanged.
- API and WebSocket endpoints: `/api`, `/api/stats`, `/status`, `/control`, `/storage`, `/config` responses unchanged.
- Logging: startup logs and run logs still written with configured format/location.
- Hardware I/O scripts: thermocouple, output relay, buzzer, and GPIO scripts still executable from root wrappers.
- UI: legacy static UI under `public/` and `ui-v2` build both function.
- Run health tooling: `./thekilngod run-health --print-only` behavior unchanged.
