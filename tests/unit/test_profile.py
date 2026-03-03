"""Unit tests for kiln profile interpolation helpers."""

from __future__ import annotations

import json
from pathlib import Path

from thekilngod.oven import Profile

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load_profile(name: str = "test_fast.json") -> Profile:
    """Load a profile fixture into the runtime Profile object."""
    with (FIXTURES_DIR / name).open(encoding="utf-8") as infile:
        profile_json = json.dumps(json.load(infile))
    return Profile(profile_json)


def test_get_target_temperature() -> None:
    """Interpolated target temperature should match expected schedule values."""
    profile = _load_profile()

    assert int(profile.get_target_temperature(3000)) == 200
    assert profile.get_target_temperature(6004) == 801.0


def test_find_time_from_temperature() -> None:
    """Temperature-to-time lookup should return deterministic checkpoints."""
    profile = _load_profile()

    assert profile.find_next_time_from_temperature(500) == 4800
    assert profile.find_next_time_from_temperature(2004) == 10857.6
    assert profile.find_next_time_from_temperature(1900) == 10400.0


def test_find_time_odd_profile() -> None:
    """Nonlinear schedules should still return stable inverse mappings."""
    profile = _load_profile("test_cases.json")

    assert profile.find_next_time_from_temperature(500) == 4200
    assert profile.find_next_time_from_temperature(2023) == 16676.0


def test_find_x_given_y_on_line_from_two_points() -> None:
    """Line interpolation should resolve expected edge and nominal cases."""
    profile = _load_profile()

    assert profile.find_x_given_y_on_line_from_two_points(500, [3600, 200], [10800, 2000]) == 4800
    assert profile.find_x_given_y_on_line_from_two_points(500, [3600, 200], [10800, 200]) == 0
    assert profile.find_x_given_y_on_line_from_two_points(500, [3600, 600], [10800, 600]) == 0
    assert profile.find_x_given_y_on_line_from_two_points(500, [3600, 500], [10800, 500]) == 0
