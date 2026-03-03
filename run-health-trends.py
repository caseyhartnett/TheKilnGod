#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import statistics
import sys

DEFAULT_HISTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), 'run-health-history.jsonl'))
DEFAULT_EXCLUSIONS = os.path.abspath(os.path.join(os.path.dirname(__file__), 'run-health-exclusions.json'))
try:
    import config  # noqa: F401
    DEFAULT_HISTORY = getattr(config, 'run_health_history_file', DEFAULT_HISTORY)
    DEFAULT_EXCLUSIONS = getattr(config, 'run_health_exclusions_file', DEFAULT_EXCLUSIONS)
except Exception:
    # Allow script usage on non-hardware/dev environments.
    pass


def load_history(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_exclusions(path):
    if not os.path.exists(path):
        return set()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            obj = json.load(f)
        if isinstance(obj, list):
            return set(str(x) for x in obj)
    except Exception:
        pass
    return set()


def parse_ts(value):
    # Supports ISO strings written by the controller
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception:
        return None


def print_summary(rows):
    if not rows:
        print("No run history found.")
        return
    last = rows[-1]
    print(f"Runs logged: {len(rows)}")
    print(f"Last run: profile={last.get('profile')} reason={last.get('reason')} ended_at={last.get('ended_at')}")

    recent = rows[-10:] if len(rows) >= 10 else rows
    gaps = [float(r.get('max_temp_gap_to_peak_target', 0.0)) for r in recent]
    high_temp_duty = [float(r.get('high_temp_duty_pct', 0.0)) for r in recent]
    within = [float(r.get('within_5deg_pct', 0.0)) for r in recent]
    print(f"Recent avg max-temp-gap-to-peak: {statistics.mean(gaps):.2f}")
    print(f"Recent avg high-temp-duty: {statistics.mean(high_temp_duty):.2f}%")
    print(f"Recent avg within±5deg: {statistics.mean(within):.2f}%")


def warning_analysis(rows):
    if len(rows) < 6:
        return "Need at least 6 runs for trend warnings."
    recent = rows[-6:]
    gaps = [float(r.get('max_temp_gap_to_peak_target', 0.0)) for r in recent]
    high_duty = [float(r.get('high_temp_duty_pct', 0.0)) for r in recent]

    gap_rising = gaps[-1] > gaps[0] + 10
    duty_rising = high_duty[-1] > high_duty[0] + 15
    if gap_rising and duty_rising:
        return ("WARNING: Trend suggests declining element performance "
                "(larger peak-temp shortfall while high-temp duty increases).")
    if gap_rising:
        return "Watch: peak-temp shortfall is rising."
    if duty_rising:
        return "Watch: high-temp relay duty is rising."
    return "No strong degradation trend detected in recent runs."


def plot(rows, output_file):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is required for plotting. Install with: pip install matplotlib")
        return 1

    dated = []
    for row in rows:
        t = parse_ts(row.get('ended_at'))
        if not t:
            continue
        dated.append((t, row))

    if not dated:
        print("No valid timestamped runs to plot.")
        return 1

    xs = [x for x, _ in dated]
    gap = [float(r.get('max_temp_gap_to_peak_target', 0.0)) for _, r in dated]
    high_duty = [float(r.get('high_temp_duty_pct', 0.0)) for _, r in dated]
    within = [float(r.get('within_5deg_pct', 0.0)) for _, r in dated]
    switches = [float(r.get('switches_per_hour', 0.0)) for _, r in dated]

    fig, axs = plt.subplots(4, 1, figsize=(12, 12), sharex=True)
    axs[0].plot(xs, gap, marker='o', color='#ef4444')
    axs[0].set_ylabel('Max Temp Gap')
    axs[0].set_title('Kiln Run Health Trends')
    axs[0].grid(True, alpha=0.3)

    axs[1].plot(xs, high_duty, marker='o', color='#f59e0b')
    axs[1].set_ylabel('High Temp Duty %')
    axs[1].grid(True, alpha=0.3)

    axs[2].plot(xs, within, marker='o', color='#22c55e')
    axs[2].set_ylabel('Within ±5° %')
    axs[2].grid(True, alpha=0.3)

    axs[3].plot(xs, switches, marker='o', color='#3b82f6')
    axs[3].set_ylabel('Switches / hour')
    axs[3].set_xlabel('Run End Time')
    axs[3].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_file, dpi=120)
    print(f"Wrote {output_file}")
    return 0


def main():
    parser = argparse.ArgumentParser(description='Plot kiln run health trends across runs.')
    parser.add_argument('--history', default=DEFAULT_HISTORY, help='Path to run health history JSONL')
    parser.add_argument('--exclusions', default=DEFAULT_EXCLUSIONS, help='Path to exclusion JSON list')
    parser.add_argument('--include-excluded', action='store_true', help='Include runs marked excluded')
    parser.add_argument('--out', default='run-health-trends.png', help='Output image file')
    parser.add_argument('--print-only', action='store_true', help='Print trend summary only, do not plot')
    args = parser.parse_args()

    rows = load_history(args.history)
    if not args.include_excluded:
        excluded = load_exclusions(args.exclusions)
        if excluded:
            rows = [row for row in rows if str(row.get('run_id', '')) not in excluded]
    print_summary(rows)
    print(warning_analysis(rows))

    if args.print_only:
        return 0
    return plot(rows, args.out)


if __name__ == '__main__':
    raise SystemExit(main())
