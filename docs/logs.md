# Logs for a Kiln Run

Application logs on the Pi are written to **`/var/log/daemon.log`** and look like this:

    May 14 22:36:09 kiln python[350]: 2022-05-14 22:36:09,824 INFO oven: temp=1888.40, target=1888.00, error=-0.40, pid=54.33, p=-3.99, i=69.11, d=-10.79, heat_on=1.09, heat_off=0.91, run_time=27250, total_time=27335, time_left=84

| Log Variable | Meaning |
| ------------ | ------- |
| `temp` | Temperature read by the thermocouple. |
| `target` | Current target temperature. |
| `error` | Difference between target and measured temperature. |
| `pid` | PID output for that control cycle. |
| `p` | Proportional term for that control cycle. |
| `i` | Integral term for that control cycle. |
| `d` | Derivative term for that control cycle. |
| `heat_on` | Seconds the elements were on during the cycle. |
| `heat_off` | Seconds the elements were off during the cycle. |
| `run_time` | Seconds since the schedule started. |
| `total_time` | Total scheduled runtime in seconds. |
| `time_left` | Seconds remaining in the schedule. |

App-managed JSON/CSV logs are stored under `storage/logs/`:

- `storage/logs/command-audit.log`
- `storage/logs/run-health-history.jsonl`
- `storage/logs/run-health-exclusions.json`
- `storage/logs/power-telemetry.jsonl`
- `storage/logs/catchup-shadow.jsonl` (shadow decisions: `normal`, `holdoff`, `would_extend`, `would_abort`)
- `storage/logs/kiln-stats.csv` (default output for `thekilngod logger`)

Per-run firing records (exact control-cycle timeline) are written to:

- `storage/logs/firings/*.csv`
- `storage/logs/firings/*.meta.json`
- `storage/logs/firings/*.summary.json`

The per-run CSV includes one `sample` row for each control cycle with fields
for runtime, measured temperature, target, error, relay on/off seconds, PID
terms, and online quality indicators (`within_5deg`, switch rate, overshoot,
sensor error rate). It also includes `start` and `end` rows so each file is a
complete firing record.

`power-telemetry.jsonl` rows include electrical measurements and control context, for example:

- `line_voltage`, `line_current`, `line_power`, `line_energy_wh`
- raw values (`line_current_raw`, `line_power_raw`, `line_energy_wh_raw`)
- `power_sensor_stale`, `power_sensor_error_percent`
- thermal context (`temperature`, `target`, `error`, `heat_on`)


If you need to send kiln logs to someone for troubleshooting:

```
cd TheKilnGod
./ziplogs
```

That creates a file named `kiln.logs.gz` in the current directory, ready to share.

For deeper troubleshooting with exported logs, see:

- https://github.com/jbruce12000/kiln-stats
