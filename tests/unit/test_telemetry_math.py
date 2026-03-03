"""Unit tests for telemetry math helpers."""

from thekilngod.telemetry_math import (
    avg,
    bool_pct,
    switch_count,
    switches_per_hour,
    within_tolerance_pct,
)


def test_avg() -> None:
    """Average should return 0.0 for empty input and mean otherwise."""
    assert avg([]) == 0.0
    assert avg([1, 2, 3]) == 2.0


def test_bool_pct() -> None:
    """Boolean percentage should map truthy values to percent scale."""
    assert bool_pct([]) == 0.0
    assert bool_pct([True, False, True, True]) == 75.0


def test_within_tolerance_pct() -> None:
    """Tolerance percentage should count values inside the absolute threshold."""
    values = [0, 2, -3, 6, -7, 5]
    assert within_tolerance_pct(values, 5) == 4 / 6 * 100
    assert within_tolerance_pct(values, 2) == 2 / 6 * 100


def test_switch_count() -> None:
    """Switch count should increment once per binary transition."""
    assert switch_count([]) == 0
    assert switch_count([0]) == 0
    assert switch_count([0, 0, 0]) == 0
    assert switch_count([0, 1, 0, 1, 1, 0]) == 4


def test_switches_per_hour() -> None:
    """Switch-rate normalization should handle zero runtime safely."""
    assert switches_per_hour(0, 0) == 0.0
    assert switches_per_hour(120, 3600) == 120.0
    assert switches_per_hour(60, 1800) == 120.0
