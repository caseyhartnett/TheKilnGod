Start a run

    curl -d '{"cmd":"run", "profile":"cone-05-long-bisque"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

Skip the first part of a run and start at minute 60

    curl -d '{"cmd":"run", "profile":"cone-05-long-bisque","startat":60}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

Stop a schedule

    curl -d '{"cmd":"stop"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

Post a memo

    curl -d '{"cmd":"memo", "memo":"some significant message"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

Stats for currently running schedule

    curl -X GET http://0.0.0.0:8081/api/stats

Pause a run (maintain current temperature until resume)

    curl -d '{"cmd":"pause"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

Resume a paused run
    
    curl -d '{"cmd":"resume"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

Auth examples:

    curl -d '{"cmd":"stop"}' -H "Content-Type: application/json" -H "X-API-Token: CONTROL_TOKEN" -X POST http://0.0.0.0:8081/api
    curl -H "X-API-Token: MONITOR_TOKEN" -X GET http://0.0.0.0:8081/api/stats

Notes:

- `POST /api` requires a JSON object body.
- Missing/unknown `cmd` values now return `400` instead of an internal server error.
- `startat` is an integer number of minutes.
- Browser websocket clients use `?token=...` for `/status`, `/storage`, `/config`, and `/control`.
