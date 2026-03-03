# UI v2

`ui-v2/` is a React + TypeScript + Vite frontend for the kiln dashboard.

## Current status

Implemented:

- Live websocket connection to `/status`
- Core telemetry cards
- Last-5-minute error chart
- Last-5-minute relay on/off chart
- Profile-aware run controls (start/pause/resume/stop)
- `startat` minute support for run resume/skip starts
- Optional control token support (`X-API-Token`) for command auth
- Optional monitor token support for websocket monitor channels (`/status`, `/storage`)
- Safety UX:
  - state-aware button enabling/disabling
  - confirmation prompts for control commands
  - stale/sensor fault warning banner
- Event timeline for key operational transitions
- Profile preflight validation before start
- Dark theme aligned with Torrify palette direction

## Run locally

```bash
cd ui-v2
npm install
npm run dev
```

By default Vite runs on `http://localhost:5173`.

## Build for kiln-controller static hosting

```bash
cd ui-v2
npm run build
```

Build output goes to:

- `public/v2/index.html`
- `public/v2/assets/*`

This is served by the existing static route and available at:

- `/v2`
- `/picoreflow/v2/index.html`

## Next steps

1. Add run controls (start/pause/resume/stop) with confirmation modals.
2. Add profile list/read view, then profile edit UX.
3. Add stale stream visual alarm and fault banners.
4. Add API polling fallback if websocket is unavailable.
5. Add auth-compatible client wrapper once backend auth is introduced.
