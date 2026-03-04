# Run Health Tracking

The controller now writes per-run health summaries to:

- `storage/logs/run-health-history.jsonl` (configurable with `run_health_history_file`)
- optional exclusions in `storage/logs/run-health-exclusions.json` (configurable with `run_health_exclusions_file`)

Each line is a JSON object with metrics useful for long-term element aging detection, including:

- `max_temp_gap_to_peak_target`
- `high_temp_duty_pct`
- `within_5deg_pct`
- `switches_per_hour`
- `overshoot_max`
- `catching_up_pct`

## Catch-Up Supervisor Shadow Log

The controller also writes catch-up supervisor shadow decisions to:

- `storage/logs/catchup-shadow.jsonl` (configurable with `catchup_shadow_log_file`)

This log is intended for threshold tuning and false-positive review before enforcement mode.

Each row includes:

- `decision`: `normal`, `holdoff`, `would_extend`, or `would_abort`
- `avg_error_confidence`
- `rise_rate_trend_deg_per_hour`
- `duty_cycle_confidence_pct`
- `lagging_seconds`
- `cusum_deg_seconds`
- `holdoff_active`

### Important Safety Note

When `catchup_supervisor_mode = "shadow"` (default), no run-control action is taken. A `would_abort` decision in this log is informational only.

## Shadow Validation Workflow

Use this sequence before considering enforcement:

1. Run several known-good firings in shadow mode.
2. Confirm there are no sustained `would_abort` decisions during successful firings.
3. Run a controlled degraded-power test (for example, disable elements) and confirm `would_abort` appears.
4. Tune thresholds in `config.py` and repeat until false-positive behavior is acceptable.

## Why this helps detect aging

A common degradation pattern is:

1. Peak temperature shortfall grows.
2. High-temperature duty cycle rises.
3. Controller spends more time trying to catch up.

If those trends increase together over many runs, element performance may be declining.

## Simple trend plotting

Use:

```bash
./thekilngod run-health
```

Output:

- `run-health-trends.png` with multi-panel trend chart

Summary-only mode:

```bash
./thekilngod run-health --print-only
```

Include excluded runs:

```bash
./thekilngod run-health --include-excluded
```

If plotting fails, install matplotlib:

```bash
pip install matplotlib
```

### Quick Checks

Show recent shadow decisions:

```bash
tail -n 30 storage/logs/catchup-shadow.jsonl
```

Show only potential abort candidates:

```bash
grep '"decision": "would_abort"' storage/logs/catchup-shadow.jsonl | tail -n 30
```

## UI

`/v2` now includes a **Run Health Trends** panel with:

- historical run count selector
- include-excluded toggle
- per-run exclusion checkbox (for special circumstances)
- trend chart for key aging indicators
