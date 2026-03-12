# UI v2

`ui-v2/` is a React + TypeScript + Vite frontend for the kiln dashboard.

## Current status

Implemented:

- Live websocket connection to `/status`
- Live profile loading and saving over `/storage`
- Core telemetry cards
- Last-5-minute error chart
- Last-5-minute relay on/off chart
- Profile-aware run controls (start/pause/resume/stop)
- `startat` minute support for run resume/skip starts
- Full-run temperature/target chart with zoom window
- Full-run current/voltage charts
- Run health trend view backed by `/api/run-health`
- Profile schedule builder with save/overwrite flow
- Optional control token support (`X-API-Token`) for command auth
- Optional monitor token support for websocket monitor channels (`/status`, `/storage`)
- Session-scoped browser token storage (with one-time fallback read from old `localStorage`)
- Optional lightweight UI lock using the `KILN_UI_PASSWORD` environment variable
- Safety UX:
  - state-aware button enabling/disabling
  - confirmation prompts for control commands
  - stale/sensor fault warning banner
- Event timeline for key operational transitions
- Profile preflight validation before start

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

## Current gaps

1. Add dedicated frontend test coverage for command flows, builder validation, and auth/token UX.
2. Handle websocket auth failures with clearer inline UI states instead of silent reconnect loops.
3. Add more explicit backlog rendering from `/status` so reconnects can repopulate charts immediately.
4. Consider replacing `window.confirm` prompts with first-class modal components.

## Optional UI Password

If the server environment defines `KILN_UI_PASSWORD`, `ui-v2` shows a password prompt before revealing telemetry and controls.

- The unlock persists for the current browser session via an HTTP-only cookie.
- If `KILN_UI_PASSWORD` is unset, the password screen is skipped automatically.
- This is a convenience/accidental-use guard for the UI only; it does not add backend API security.
