"""Unit tests for firing analyzer integration and cone estimation."""

from __future__ import annotations

import json
from pathlib import Path

from thekilngod.firing_analyzer import (
    build_cone_references,
    estimate_cone,
    fahrenheit_to_kelvin,
    integrate_heatwork,
    parse_csv_log,
    profile_points_to_samples,
)


def _write_profile(path: Path, name: str, data: list[list[float]]) -> None:
    profile = {"name": name, "type": "profile", "temp_units": "f", "data": data}
    path.write_text(json.dumps(profile), encoding="utf-8")


def test_hotter_profile_has_higher_heatwork() -> None:
    ref_k = fahrenheit_to_kelvin(2232.0)
    low_samples = profile_points_to_samples([[0, 75], [3600, 1400], [7200, 1850]], "f")
    high_samples = profile_points_to_samples([[0, 75], [3600, 1600], [7200, 2232]], "f")

    low_work = integrate_heatwork(low_samples, e_over_r=38000.0, reference_temp_k=ref_k)
    high_work = integrate_heatwork(high_samples, e_over_r=38000.0, reference_temp_k=ref_k)

    assert high_work > low_work


def test_estimate_cone_uses_reference_profiles(tmp_path: Path) -> None:
    ref_k = fahrenheit_to_kelvin(2232.0)

    cone_04 = tmp_path / "cone-04-custom.json"
    cone_6 = tmp_path / "cone-6-custom.json"
    _write_profile(cone_04, "cone-04-custom", [[0, 75], [3600, 1400], [7200, 1945]])
    _write_profile(cone_6, "cone-6-custom", [[0, 75], [3600, 1600], [7200, 2232]])

    references, warnings = build_cone_references(tmp_path, e_over_r=38000.0, reference_temp_k=ref_k)
    assert not warnings
    assert [reference.cone_label for reference in references] == ["04", "6"]

    target_samples = profile_points_to_samples([[0, 75], [3600, 1580], [7200, 2200]], "f")
    target_work = integrate_heatwork(target_samples, e_over_r=38000.0, reference_temp_k=ref_k)
    estimate = estimate_cone(target_work, references)

    assert estimate.nearest_label == "6"
    assert estimate.lower_label == "04"
    assert estimate.upper_label == "6"


def test_parse_csv_log_splits_multiple_runs(tmp_path: Path) -> None:
    csv_path = tmp_path / "runs.csv"
    csv_path.write_text(
        "\n".join(
            [
                "runtime_s,temperature",
                "0,100",
                "10,200",
                "0,300",
                "10,400",
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_csv_log(
        csv_path,
        temp_units="f",
        run_select="last",
        runtime_column=None,
        temperature_column=None,
    )

    assert parsed.run_count == 2
    assert parsed.selected_run_index == 1
    assert len(parsed.samples) == 2
    assert round(parsed.samples[0].seconds) == 0
    assert round(parsed.samples[1].seconds) == 10
