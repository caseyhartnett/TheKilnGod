# Run Health Tracking

The controller now writes per-run health summaries to:

- `run-health-history.jsonl` (configurable with `run_health_history_file`)
- optional exclusions in `run-health-exclusions.json` (configurable with `run_health_exclusions_file`)

Each line is a JSON object with metrics useful for long-term element aging detection, including:

- `max_temp_gap_to_peak_target`
- `high_temp_duty_pct`
- `within_5deg_pct`
- `switches_per_hour`
- `overshoot_max`
- `catching_up_pct`

## Why this helps detect aging

A common degradation pattern is:

1. Peak temperature shortfall grows.
2. High-temperature duty cycle rises.
3. Controller spends more time trying to catch up.

If those trends increase together over many runs, element performance may be declining.

## Simple trend plotting

Use:

```bash
python3 run-health-trends.py
```

Output:

- `run-health-trends.png` with multi-panel trend chart

Summary-only mode:

```bash
python3 run-health-trends.py --print-only
```

Include excluded runs:

```bash
python3 run-health-trends.py --include-excluded
```

If plotting fails, install matplotlib:

```bash
pip install matplotlib
```

## UI

`/v2` now includes a **Run Health Trends** panel with:

- historical run count selector
- include-excluded toggle
- per-run exclusion checkbox (for special circumstances)
- trend chart for key aging indicators
