from collections.abc import Sequence


def avg(values: Sequence[float]) -> float:
    """Return arithmetic mean, defaulting to 0.0 for empty samples.

    Returning 0.0 avoids special-case checks in telemetry pipelines that
    aggregate sparse run windows.
    """
    if not values:
        return 0.0
    return sum(values) / float(len(values))


def bool_pct(values: Sequence[bool]) -> float:
    """Convert a truthy sequence into a percent.

    The control loop stores multiple boolean health checks; percent is the
    most stable summary across windows with varying sample counts.
    """
    if not values:
        return 0.0
    return avg([1.0 if v else 0.0 for v in values]) * 100.0


def within_tolerance_pct(values: Sequence[float], tolerance: float) -> float:
    """Return the percent of values that stay within the tolerance band."""
    if not values:
        return 0.0
    return (sum(1 for value in values if abs(value) <= tolerance) / float(len(values))) * 100.0


def switch_count(binary_values: Sequence[bool | int]) -> int:
    """Count state transitions in a binary series.

    Transition count is used as a wear proxy for relays and contactors.
    """
    if len(binary_values) <= 1:
        return 0
    count = 0
    prev = 1 if binary_values[0] else 0
    for value in binary_values[1:]:
        now = 1 if value else 0
        if now != prev:
            count += 1
        prev = now
    return count


def switches_per_hour(total_switches: int, runtime_seconds: float) -> float:
    """Normalize switching counts by runtime for cross-run comparability."""
    if runtime_seconds <= 0:
        return 0.0
    return float(total_switches) / (float(runtime_seconds) / 3600.0)
