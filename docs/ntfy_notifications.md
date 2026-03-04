# ntfy Notifications Setup

This project now supports outbound push notifications through `ntfy`.

## 1) Configure `config.py` + `secrets.py`

Set defaults in `config.py` and keep secrets in `secrets.py`:

```python
notifications_enabled = True
notification_provider = "ntfy"
ntfy_server = "https://ntfy.sh"
ntfy_topic = "your-unique-kiln-topic"
# Optional for private/protected topic:
# ntfy_access_token = "your_ntfy_access_token"
```

Recommended:
- non-sensitive defaults in `config.py`
- `ntfy_access_token` and private topic names in `secrets.py`

Recommended: use a long, hard-to-guess topic string.

## 2) Subscribe on your phone

Use either:
- ntfy mobile app (Android/iOS), or
- browser at `https://ntfy.sh/your-unique-kiln-topic`

## 3) Restart kiln controller

After restart, the background notification worker is enabled.

## 4) Trigger a test event

Start and stop a profile from UI/API. You should receive:
- Run started
- Run paused/resumed
- Run stopped/completed
- Emergency stop alerts (if they occur)
- Profile segment (rate) change checkpoints
- Temperature milestones (every 500 degrees by default)
- Abnormal deviation alert (rapid temp drop while heating)
- Catch-up shadow advisories (`would_extend` / `would_abort`) when shadow mode is enabled

## 5) Optional alert tuning

Tune these values in `config.py`:

```python
# Send milestone at each N degrees
notifications_temp_milestone_interval = 500

# Deviation detection
notifications_deviation_drop_window_seconds = 45
notifications_deviation_drop_threshold = 20
notifications_deviation_min_error = 35
notifications_deviation_min_target_temp = 300
notifications_deviation_cooldown_seconds = 300
```

## 6) Optional direct topic test from shell

```bash
curl -H "Title: Kiln Test" -d "ntfy path works" https://ntfy.sh/your-unique-kiln-topic
```
