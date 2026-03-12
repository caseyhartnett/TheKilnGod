"""Unit tests for per-run firing record writer."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from thekilngod.firing_record import FiringRecordWriter


def _read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8", newline="") as infile:
        reader = csv.DictReader(infile)
        return list(reader)


def test_firing_record_writer_creates_csv_meta_and_summary(tmp_path: Path) -> None:
    writer = FiringRecordWriter(enabled=True, output_dir=tmp_path, flush_each_row=True)

    csv_path_str = writer.start_run(
        run_id="run-12345",
        profile_name="cone-6-standard",
        startat_seconds=0.0,
        total_seconds=3600.0,
        metadata={"temp_scale": "f"},
    )
    assert csv_path_str is not None
    csv_path = Path(csv_path_str)
    assert csv_path.exists()

    writer.write_sample(
        {
            "row_type": "sample",
            "run_id": "run-12345",
            "profile": "cone-6-standard",
            "runtime_s": 120.0,
            "total_s": 3600.0,
            "temperature": 432.1,
            "target": 430.0,
            "heat_on_s": 1.2,
            "heat_off_s": 0.8,
            "relay_on": True,
        }
    )
    writer.end_run(
        "schedule_complete",
        {
            "run_id": "run-12345",
            "profile": "cone-6-standard",
            "reason_text": "Reached the end of the firing plan",
            "reason_kind": "complete",
            "runtime_seconds": 3600.0,
            "runtime_hours": 1.0,
            "completed": True,
            "within_5deg_pct": 92.0,
            "switch_count": 55,
            "switches_per_hour": 55.0,
            "overshoot_max": 8.0,
            "max_temp": 2232.0,
            "max_target": 2232.0,
            "peak_profile_target": 2232.0,
            "max_temp_gap_to_peak_target": 0.0,
            "heat_duty_pct": 64.0,
            "high_temp_seconds": 600.0,
            "high_temp_duty_pct": 75.0,
            "high_temp_mae": 2.1,
            "catching_up_seconds": 90.0,
            "catching_up_pct": 2.5,
            "sensor_error_rate_5m": 0.0,
            "cost": 3.42,
        },
    )
    writer.close()

    rows = _read_rows(csv_path)
    assert len(rows) == 3
    assert rows[0]["row_type"] == "start"
    assert rows[1]["row_type"] == "sample"
    assert rows[2]["row_type"] == "end"
    assert rows[1]["temperature"] == "432.1"
    assert rows[1]["relay_on"] in {"True", "1"}
    assert rows[2]["reason"] == "schedule_complete"
    assert rows[2]["reason_text"] == "Reached the end of the firing plan"
    assert rows[2]["reason_kind"] == "complete"
    assert rows[2]["completed"] in {"True", "1"}

    meta_path = csv_path.with_suffix(".meta.json")
    summary_path = csv_path.with_suffix(".summary.json")
    assert meta_path.exists()
    assert summary_path.exists()

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert meta["run_id"] == "run-12345"
    assert summary["run_id"] == "run-12345"
    assert summary["reason_text"] == "Reached the end of the firing plan"


def test_disabled_writer_no_files(tmp_path: Path) -> None:
    writer = FiringRecordWriter(enabled=False, output_dir=tmp_path, flush_each_row=True)
    csv_path = writer.start_run(
        run_id="disabled",
        profile_name="cone-6",
        startat_seconds=0,
        total_seconds=10,
        metadata=None,
    )
    assert csv_path is None
    assert list(tmp_path.glob("*")) == []
