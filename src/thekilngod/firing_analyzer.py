#!/usr/bin/env python3
"""Estimate cone-equivalent heatwork from kiln plans or run logs.

The analyzer computes a temperature-time integral using an Arrhenius-like
reaction rate model so high-temperature soak contributes far more than low
temperature ramping. It then maps the result onto cone-equivalent thresholds
derived from local `cone-*.json` profiles.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE_PROFILES = REPO_ROOT / "storage" / "profiles"
CONE_NAME_RE = re.compile(r"^cone-([0-9]+)(?:$|[-_])", re.IGNORECASE)
DAEMON_LOG_RE = re.compile(
    r"temp=(?P<temp>-?\d+(?:\.\d+)?).*run_time=(?P<runtime>-?\d+(?:\.\d+)?)"
)


@dataclass(frozen=True)
class Sample:
    """Time/temperature sample for integration."""

    seconds: float
    temp_k: float


@dataclass(frozen=True)
class ParsedLog:
    """Parsed run-log payload with run segmentation metadata."""

    samples: list[Sample]
    row_count: int
    run_count: int
    selected_run_index: int


@dataclass(frozen=True)
class ConeReference:
    """Cone reference level represented by median profile heatwork."""

    cone_numeric: int
    cone_label: str
    heatwork_seconds: float
    profile_count: int


@dataclass(frozen=True)
class ConeEstimate:
    """Estimated cone position for a measured heatwork integral."""

    nearest_label: str
    lower_label: str
    upper_label: str
    lower_numeric: int
    upper_numeric: int
    interval_fraction: float
    continuous_numeric: float
    range_status: str


def fahrenheit_to_kelvin(temp_f: float) -> float:
    """Convert Fahrenheit to Kelvin."""
    return (temp_f - 32.0) * (5.0 / 9.0) + 273.15


def celsius_to_kelvin(temp_c: float) -> float:
    """Convert Celsius to Kelvin."""
    return temp_c + 273.15


def kelvin_to_fahrenheit(temp_k: float) -> float:
    """Convert Kelvin to Fahrenheit."""
    return (temp_k - 273.15) * (9.0 / 5.0) + 32.0


def parse_float(value: Any) -> float | None:
    """Best-effort float conversion for mixed text/CSV values."""
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def extract_cone_label(profile_name: str) -> str | None:
    """Extract the cone token from names like `cone-6-standard`."""
    match = CONE_NAME_RE.match(profile_name.strip())
    if not match:
        return None
    return match.group(1)


def cone_label_to_numeric(cone_label: str) -> int:
    """Map cone label text into an ordered numeric scale.

    Low-fire cones with leading zero notation become negative integers:
    `022 -> -22`, `04 -> -4`, `6 -> 6`.
    """
    token = cone_label.strip()
    if not token.isdigit():
        msg = f"Invalid cone label: {cone_label}"
        raise ValueError(msg)
    numeric = int(token)
    if token.startswith("0") and len(token) > 1:
        return -numeric
    return numeric


def cone_numeric_to_label(cone_numeric: int) -> str:
    """Render ordered numeric cone value back to kiln-style notation."""
    if cone_numeric < 0:
        magnitude = abs(cone_numeric)
        if magnitude >= 10:
            return f"0{magnitude:02d}"
        return f"0{magnitude}"
    return str(cone_numeric)


def profile_points_to_samples(data: list[Any], temp_units: str) -> list[Sample]:
    """Convert profile `[time, temp]` points to normalized Kelvin samples."""
    raw: list[tuple[float, float]] = []
    units = temp_units.lower()
    if units not in {"f", "c"}:
        msg = f"Unsupported profile temp_units={temp_units!r}; expected 'f' or 'c'"
        raise ValueError(msg)

    for point in data:
        if not isinstance(point, list | tuple) or len(point) < 2:
            continue
        seconds = parse_float(point[0])
        temp = parse_float(point[1])
        if seconds is None or temp is None:
            continue
        temp_k = fahrenheit_to_kelvin(temp) if units == "f" else celsius_to_kelvin(temp)
        raw.append((seconds, temp_k))
    return normalize_single_run(raw)


def infer_profile_temp_units(data: list[Any]) -> str:
    """Infer profile units when legacy profiles omit `temp_units`.

    Heuristic:
    - Peaks above 1400 are treated as Fahrenheit (too high for typical cone C).
    - Very low test ramps (<350 peak) are also treated as Fahrenheit.
    - Otherwise default to Celsius for newer canonical profile storage.
    """
    temperatures: list[float] = []
    for point in data:
        if not isinstance(point, list | tuple) or len(point) < 2:
            continue
        temp = parse_float(point[1])
        if temp is not None:
            temperatures.append(temp)

    if not temperatures:
        return "f"
    peak = max(temperatures)
    if peak > 1400 or peak < 350:
        return "f"
    return "c"


def normalize_single_run(raw_samples: list[tuple[float, float]]) -> list[Sample]:
    """Sort a single run and collapse duplicate timestamps."""
    if not raw_samples:
        return []
    by_time: dict[float, float] = {}
    for seconds, temp_k in raw_samples:
        by_time[seconds] = temp_k
    ordered = sorted(by_time.items())
    return [Sample(seconds=seconds, temp_k=temp_k) for seconds, temp_k in ordered]


def split_runs(raw_samples: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    """Split samples into runs whenever runtime decreases."""
    runs: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    previous_seconds: float | None = None

    for seconds, temp_k in raw_samples:
        if previous_seconds is not None and seconds < previous_seconds:
            if current:
                runs.append(current)
            current = []
        current.append((seconds, temp_k))
        previous_seconds = seconds

    if current:
        runs.append(current)
    return runs


def choose_run(
    runs: list[list[tuple[float, float]]], run_select: str
) -> tuple[list[tuple[float, float]], int]:
    """Select the target run from segmented log runs."""
    if not runs:
        msg = "No valid runtime samples were found in log"
        raise ValueError(msg)
    if run_select == "longest":
        index = max(range(len(runs)), key=lambda idx: len(runs[idx]))
    else:
        index = len(runs) - 1
    return runs[index], index


def choose_column(fieldnames: list[str], requested: str | None, candidates: tuple[str, ...]) -> str:
    """Resolve a CSV column by explicit name or candidate fallback list."""
    lowercase_map = {name.lower(): name for name in fieldnames}

    if requested:
        direct = requested if requested in fieldnames else None
        lowered = lowercase_map.get(requested.lower())
        chosen = direct or lowered
        if chosen:
            return chosen
        msg = f"CSV column {requested!r} was not found. Available: {', '.join(fieldnames)}"
        raise ValueError(msg)

    for candidate in candidates:
        if candidate in fieldnames:
            return candidate
        lowered = lowercase_map.get(candidate.lower())
        if lowered:
            return lowered
    msg = f"Could not find any of columns {candidates}. Available: {', '.join(fieldnames)}"
    raise ValueError(msg)


def parse_csv_log(
    log_path: Path,
    temp_units: str,
    run_select: str,
    runtime_column: str | None,
    temperature_column: str | None,
) -> ParsedLog:
    """Parse `kiln-stats.csv`-style logs into a selected run."""
    with log_path.open(encoding="utf-8", newline="") as infile:
        reader = csv.DictReader(infile)
        fieldnames = list(reader.fieldnames or [])
        if not fieldnames:
            msg = f"CSV log {log_path} has no header row"
            raise ValueError(msg)

        runtime_col = choose_column(
            fieldnames,
            runtime_column,
            ("runtime", "runtime_s", "run_time", "seconds"),
        )
        temp_col = choose_column(fieldnames, temperature_column, ("temperature", "temp"))

        raw: list[tuple[float, float]] = []
        row_count = 0
        for row in reader:
            row_count += 1
            seconds = parse_float(row.get(runtime_col))
            temp = parse_float(row.get(temp_col))
            if seconds is None or temp is None:
                continue
            temp_k = fahrenheit_to_kelvin(temp) if temp_units == "f" else celsius_to_kelvin(temp)
            raw.append((seconds, temp_k))

    runs = split_runs(raw)
    selected_run, selected_index = choose_run(runs, run_select)
    samples = normalize_single_run(selected_run)
    if len(samples) < 2:
        msg = f"Selected CSV run in {log_path} does not have enough points for integration"
        raise ValueError(msg)

    return ParsedLog(
        samples=samples,
        row_count=row_count,
        run_count=len(runs),
        selected_run_index=selected_index,
    )


def parse_daemon_log(log_path: Path, temp_units: str, run_select: str) -> ParsedLog:
    """Parse `/var/log/daemon.log` style lines into a selected run."""
    raw: list[tuple[float, float]] = []
    with log_path.open(encoding="utf-8") as infile:
        lines = infile.readlines()

    for line in lines:
        match = DAEMON_LOG_RE.search(line)
        if not match:
            continue
        runtime = parse_float(match.group("runtime"))
        temp = parse_float(match.group("temp"))
        if runtime is None or temp is None:
            continue
        temp_k = fahrenheit_to_kelvin(temp) if temp_units == "f" else celsius_to_kelvin(temp)
        raw.append((runtime, temp_k))

    runs = split_runs(raw)
    selected_run, selected_index = choose_run(runs, run_select)
    samples = normalize_single_run(selected_run)
    if len(samples) < 2:
        msg = f"Selected daemon log run in {log_path} does not have enough points for integration"
        raise ValueError(msg)

    return ParsedLog(
        samples=samples,
        row_count=len(lines),
        run_count=len(runs),
        selected_run_index=selected_index,
    )


def detect_log_format(log_path: Path) -> str:
    """Infer log format when `--log-format auto` is used."""
    if log_path.suffix.lower() == ".csv":
        return "csv"
    with log_path.open(encoding="utf-8") as infile:
        first_line = infile.readline().lower()
    if "," in first_line and (
        "runtime" in first_line or "runtime_s" in first_line or "temperature" in first_line
    ):
        return "csv"
    return "daemon"


def rate_weight(temp_k: float, e_over_r: float, reference_temp_k: float) -> float:
    """Return relative reaction rate at `temp_k` compared to reference temperature."""
    safe_temp_k = max(temp_k, 1.0)
    exponent = e_over_r * ((1.0 / reference_temp_k) - (1.0 / safe_temp_k))
    exponent = max(-80.0, min(80.0, exponent))
    return math.exp(exponent)


def integrate_heatwork(samples: list[Sample], e_over_r: float, reference_temp_k: float) -> float:
    """Integrate Arrhenius-weighted thermal work over a run profile."""
    if len(samples) < 2:
        msg = "Need at least two samples to integrate heatwork"
        raise ValueError(msg)

    total = 0.0
    for sample_a, sample_b in pairwise(samples):
        delta_seconds = sample_b.seconds - sample_a.seconds
        if delta_seconds <= 0:
            continue
        weight_a = rate_weight(sample_a.temp_k, e_over_r, reference_temp_k)
        weight_b = rate_weight(sample_b.temp_k, e_over_r, reference_temp_k)
        total += 0.5 * (weight_a + weight_b) * delta_seconds
    return total


def load_profile(profile_path: Path) -> tuple[str, list[Sample]]:
    """Load a profile JSON file into normalized integration samples."""
    with profile_path.open(encoding="utf-8") as infile:
        profile_obj = json.load(infile)
    if not isinstance(profile_obj, dict):
        msg = f"Profile {profile_path} is not a JSON object"
        raise ValueError(msg)

    profile_name = str(profile_obj.get("name", profile_path.stem))
    data = profile_obj.get("data", [])
    temp_units_raw = profile_obj.get("temp_units")
    temp_units = infer_profile_temp_units(data) if temp_units_raw is None else str(temp_units_raw)
    if not isinstance(data, list):
        msg = f"Profile {profile_path} has invalid data format"
        raise ValueError(msg)

    samples = profile_points_to_samples(data, temp_units)
    if len(samples) < 2:
        msg = f"Profile {profile_path} does not have enough valid points"
        raise ValueError(msg)
    return profile_name, samples


def build_cone_references(
    profiles_dir: Path, e_over_r: float, reference_temp_k: float
) -> tuple[list[ConeReference], list[str]]:
    """Build cone threshold table from local `cone-*.json` profiles."""
    grouped: dict[int, list[float]] = {}
    warnings: list[str] = []

    for profile_path in sorted(profiles_dir.glob("*.json")):
        try:
            profile_name, samples = load_profile(profile_path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue

        cone_label = extract_cone_label(profile_name) or extract_cone_label(profile_path.stem)
        if not cone_label:
            continue

        cone_numeric = cone_label_to_numeric(cone_label)
        heatwork_seconds = integrate_heatwork(samples, e_over_r, reference_temp_k)
        grouped.setdefault(cone_numeric, []).append(heatwork_seconds)

    if len(grouped) < 2:
        msg = (
            "Need at least two cone references. "
            f"Found {len(grouped)} in {profiles_dir}."
        )
        raise ValueError(msg)

    references: list[ConeReference] = []
    for cone_numeric in sorted(grouped):
        references.append(
            ConeReference(
                cone_numeric=cone_numeric,
                cone_label=cone_numeric_to_label(cone_numeric),
                heatwork_seconds=float(statistics.median(grouped[cone_numeric])),
                profile_count=len(grouped[cone_numeric]),
            )
        )

    smoothed: list[ConeReference] = []
    last_heatwork = -math.inf
    for reference in references:
        heatwork = reference.heatwork_seconds
        if heatwork <= last_heatwork:
            adjusted = last_heatwork + 1e-6
            warnings.append(
                "Adjusted non-monotonic reference heatwork at cone "
                f"{reference.cone_label}: {heatwork:.3f} -> {adjusted:.3f}"
            )
            heatwork = adjusted
        smoothed.append(
            ConeReference(
                cone_numeric=reference.cone_numeric,
                cone_label=reference.cone_label,
                heatwork_seconds=heatwork,
                profile_count=reference.profile_count,
            )
        )
        last_heatwork = heatwork
    return smoothed, warnings


def estimate_cone(heatwork_seconds: float, references: list[ConeReference]) -> ConeEstimate:
    """Estimate cone interval and nearest cone from heatwork value."""
    if len(references) < 2:
        msg = "Need at least two cone references for estimation"
        raise ValueError(msg)

    range_status = "within"
    lower = references[0]
    upper = references[1]

    if heatwork_seconds <= references[0].heatwork_seconds:
        range_status = "below"
        lower = references[0]
        upper = references[1]
    elif heatwork_seconds >= references[-1].heatwork_seconds:
        range_status = "above"
        lower = references[-2]
        upper = references[-1]
    else:
        for candidate_lower, candidate_upper in pairwise(references):
            if (
                candidate_lower.heatwork_seconds
                <= heatwork_seconds
                <= candidate_upper.heatwork_seconds
            ):
                lower = candidate_lower
                upper = candidate_upper
                break

    span = upper.heatwork_seconds - lower.heatwork_seconds
    fraction = 0.0 if span <= 0 else (heatwork_seconds - lower.heatwork_seconds) / span
    continuous = lower.cone_numeric + fraction * (upper.cone_numeric - lower.cone_numeric)
    nearest = min(
        references,
        key=lambda reference: abs(reference.heatwork_seconds - heatwork_seconds),
    )

    return ConeEstimate(
        nearest_label=nearest.cone_label,
        lower_label=lower.cone_label,
        upper_label=upper.cone_label,
        lower_numeric=lower.cone_numeric,
        upper_numeric=upper.cone_numeric,
        interval_fraction=fraction,
        continuous_numeric=continuous,
        range_status=range_status,
    )


def print_reference_table(references: list[ConeReference], reference_temp_f: float) -> None:
    """Print cone reference thresholds used for interpolation."""
    print("\nCone reference table")
    print(f"(heatwork shown as equivalent seconds at {reference_temp_f:.1f}F)")
    print(f"{'cone':>6} {'profiles':>8} {'heatwork_s':>14} {'eq_min':>12}")
    for reference in references:
        print(
            f"{reference.cone_label:>6} {reference.profile_count:>8} "
            f"{reference.heatwork_seconds:>14.3f} {reference.heatwork_seconds / 60.0:>12.3f}"
        )


def print_result(
    heading: str,
    samples: list[Sample],
    estimate: ConeEstimate,
    heatwork_seconds: float,
    reference_temp_f: float,
    extra_line: str | None = None,
) -> None:
    """Print one profile/log analysis block."""
    duration_seconds = samples[-1].seconds - samples[0].seconds
    peak_f = kelvin_to_fahrenheit(max(sample.temp_k for sample in samples))
    in_interval_label = (
        estimate.upper_label if estimate.interval_fraction >= 0.5 else estimate.lower_label
    )

    print(f"\n{heading}")
    if extra_line:
        print(extra_line)
    print(
        "points="
        f"{len(samples)} duration_h={duration_seconds / 3600.0:.2f} "
        f"peak_f={peak_f:.1f}"
    )
    print(
        f"heatwork_eq_seconds_at_{reference_temp_f:.1f}F={heatwork_seconds:.3f} "
        f"(eq_minutes={heatwork_seconds / 60.0:.3f})"
    )

    if estimate.range_status == "within":
        progress = max(0.0, min(1.0, estimate.interval_fraction)) * 100.0
        print(
            "estimated_cone="
            f"{in_interval_label} "
            f"(between cone {estimate.lower_label} and cone {estimate.upper_label}, "
            f"{progress:.1f}% toward cone {estimate.upper_label}; "
            f"nearest cone {estimate.nearest_label})"
        )
        return

    direction = "below" if estimate.range_status == "below" else "above"
    print(
        "estimated_cone="
        f"{estimate.nearest_label} "
        f"({direction} calibrated range; nearest cone {estimate.nearest_label}, "
        f"edge interval cone {estimate.lower_label}->{estimate.upper_label})"
    )


def resolve_profile_path(profile_arg: str, reference_profiles: Path) -> Path:
    """Resolve a profile CLI argument as path or profile name."""
    candidate = Path(profile_arg).expanduser()
    if candidate.exists():
        return candidate

    if not candidate.suffix:
        by_name = reference_profiles / f"{profile_arg}.json"
        if by_name.exists():
            return by_name
    msg = f"Profile not found: {profile_arg}"
    raise ValueError(msg)


def analyze_profile(
    profile_path: Path,
    references: list[ConeReference],
    e_over_r: float,
    reference_temp_k: float,
    reference_temp_f: float,
) -> None:
    """Analyze a plan profile file and print cone estimate."""
    profile_name, samples = load_profile(profile_path)
    heatwork_seconds = integrate_heatwork(samples, e_over_r, reference_temp_k)
    estimate = estimate_cone(heatwork_seconds, references)
    print_result(
        heading=f"Plan profile: {profile_name} ({profile_path})",
        samples=samples,
        estimate=estimate,
        heatwork_seconds=heatwork_seconds,
        reference_temp_f=reference_temp_f,
    )


def parse_log(
    log_path: Path,
    log_format: str,
    temp_units: str,
    run_select: str,
    runtime_column: str | None,
    temperature_column: str | None,
) -> ParsedLog:
    """Parse a log path according to requested or inferred format."""
    format_to_use = log_format if log_format != "auto" else detect_log_format(log_path)
    if format_to_use == "csv":
        return parse_csv_log(
            log_path=log_path,
            temp_units=temp_units,
            run_select=run_select,
            runtime_column=runtime_column,
            temperature_column=temperature_column,
        )
    return parse_daemon_log(log_path=log_path, temp_units=temp_units, run_select=run_select)


def analyze_log(
    log_path: Path,
    references: list[ConeReference],
    e_over_r: float,
    reference_temp_k: float,
    reference_temp_f: float,
    log_format: str,
    temp_units: str,
    run_select: str,
    runtime_column: str | None,
    temperature_column: str | None,
) -> None:
    """Analyze a run log file and print cone estimate."""
    parsed = parse_log(
        log_path=log_path,
        log_format=log_format,
        temp_units=temp_units,
        run_select=run_select,
        runtime_column=runtime_column,
        temperature_column=temperature_column,
    )
    heatwork_seconds = integrate_heatwork(parsed.samples, e_over_r, reference_temp_k)
    estimate = estimate_cone(heatwork_seconds, references)
    run_info = (
        f"rows={parsed.row_count} runs_in_file={parsed.run_count} "
        f"selected_run={parsed.selected_run_index + 1}"
    )
    print_result(
        heading=f"Run log: {log_path}",
        samples=parsed.samples,
        estimate=estimate,
        heatwork_seconds=heatwork_seconds,
        reference_temp_f=reference_temp_f,
        extra_line=run_info,
    )


def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser for firing analyzer script."""
    parser = argparse.ArgumentParser(
        description=(
            "Estimate kiln cone-equivalent heatwork from a profile plan and/or run log."
        )
    )
    parser.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Profile JSON path or profile name (can be passed multiple times).",
    )
    parser.add_argument(
        "--log",
        action="append",
        default=[],
        help="Run log path (CSV from kiln_logger or daemon.log style text).",
    )
    parser.add_argument(
        "--reference-profiles",
        type=Path,
        default=DEFAULT_REFERENCE_PROFILES,
        help=(
            "Directory of cone profiles used for calibration "
            f"(default: {DEFAULT_REFERENCE_PROFILES})."
        ),
    )
    parser.add_argument(
        "--reference-temp-f",
        type=float,
        default=2232.0,
        help="Reference temperature for equivalent-seconds output (default: 2232F).",
    )
    parser.add_argument(
        "--activation-energy-over-r",
        type=float,
        default=38000.0,
        help="Arrhenius activation-energy ratio E/R in Kelvin (default: 38000).",
    )
    parser.add_argument(
        "--show-reference-table",
        action="store_true",
        help="Print cone calibration table before analyses.",
    )
    parser.add_argument(
        "--log-format",
        choices=("auto", "csv", "daemon"),
        default="auto",
        help="Input format for --log files (default: auto).",
    )
    parser.add_argument(
        "--log-temp-units",
        choices=("f", "c"),
        default="f",
        help="Temperature units used in log files (default: f).",
    )
    parser.add_argument(
        "--run-select",
        choices=("last", "longest"),
        default="last",
        help="If a log contains multiple runs, choose the last or longest run.",
    )
    parser.add_argument(
        "--runtime-column",
        default=None,
        help="CSV runtime column override (default: runtime/run_time).",
    )
    parser.add_argument(
        "--temperature-column",
        default=None,
        help="CSV temperature column override (default: temperature/temp).",
    )
    return parser


def main() -> int:
    """Run CLI analyzer."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.profile and not args.log:
        parser.error("provide at least one --profile or --log input")

    reference_profiles = Path(args.reference_profiles).expanduser()
    if not reference_profiles.exists():
        parser.error(f"reference profile directory does not exist: {reference_profiles}")

    reference_temp_f = float(args.reference_temp_f)
    reference_temp_k = fahrenheit_to_kelvin(reference_temp_f)
    e_over_r = float(args.activation_energy_over_r)

    try:
        references, warnings = build_cone_references(
            reference_profiles,
            e_over_r=e_over_r,
            reference_temp_k=reference_temp_k,
        )
    except ValueError as exc:
        print(f"Failed to build cone references: {exc}", file=sys.stderr)
        return 2

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if args.show_reference_table:
        print_reference_table(references, reference_temp_f)

    failures = 0
    for profile_arg in args.profile:
        try:
            profile_path = resolve_profile_path(str(profile_arg), reference_profiles)
            analyze_profile(
                profile_path=profile_path,
                references=references,
                e_over_r=e_over_r,
                reference_temp_k=reference_temp_k,
                reference_temp_f=reference_temp_f,
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            failures += 1
            print(f"profile error [{profile_arg}]: {exc}", file=sys.stderr)

    for log_arg in args.log:
        try:
            log_path = Path(str(log_arg)).expanduser()
            analyze_log(
                log_path=log_path,
                references=references,
                e_over_r=e_over_r,
                reference_temp_k=reference_temp_k,
                reference_temp_f=reference_temp_f,
                log_format=str(args.log_format),
                temp_units=str(args.log_temp_units),
                run_select=str(args.run_select),
                runtime_column=args.runtime_column,
                temperature_column=args.temperature_column,
            )
        except (OSError, ValueError) as exc:
            failures += 1
            print(f"log error [{log_arg}]: {exc}", file=sys.stderr)

    if failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
