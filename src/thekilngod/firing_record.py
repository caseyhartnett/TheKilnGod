"""Persistent per-run firing record writer.

This module writes an exact cycle-by-cycle CSV log for each firing run and a
metadata sidecar JSON file that captures profile/config context.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import os
import re
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = "kiln_firing_record_v1"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "storage" / "logs" / "firings"

FIRING_RECORD_COLUMNS = [
    "row_type",
    "ts_utc",
    "epoch_s",
    "run_id",
    "profile",
    "state",
    "reason",
    "runtime_s",
    "total_s",
    "time_left_s",
    "startat_s",
    "temperature",
    "target",
    "error",
    "abs_error",
    "within_5deg",
    "catching_up",
    "relay_on",
    "heat_on_s",
    "heat_off_s",
    "pid_out",
    "pid_raw",
    "pid_p",
    "pid_i",
    "pid_d",
    "pid_kp",
    "pid_ki",
    "pid_kd",
    "heat_rate_deg_per_hour",
    "cost",
    "sensor_error_pct",
    "switch_count_run",
    "switches_per_hour_run",
    "overshoot_max_run",
    "runtime_hours",
    "max_temp",
    "max_target",
    "peak_profile_target",
    "max_temp_gap_to_peak_target",
    "heat_duty_pct",
    "high_temp_seconds",
    "high_temp_duty_pct",
    "high_temp_mae",
    "catching_up_seconds",
    "catching_up_pct",
    "completed",
    "notes",
]


def utc_iso(ts: float | None = None) -> str:
    """Return ISO-8601 UTC timestamp string with millisecond precision."""
    if ts is None:
        current = dt.datetime.now(dt.timezone.utc)
    else:
        current = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
    return current.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sanitize_for_filename(value: str) -> str:
    """Convert arbitrary text into a filesystem-safe token."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    safe = re.sub(r"-{2,}", "-", safe).strip("-")
    return safe or "run"


class FiringRecordWriter:
    """Append-only writer for per-run firing CSV records."""

    def __init__(
        self,
        *,
        enabled: bool,
        output_dir: str | os.PathLike[str] | None = None,
        flush_each_row: bool = True,
    ) -> None:
        """Initialize the writer with output location and durability options."""
        self.enabled = enabled
        self.flush_each_row = flush_each_row
        self.output_dir = Path(output_dir).expanduser() if output_dir else DEFAULT_OUTPUT_DIR
        self.current_csv_path: str | None = None
        self.current_meta_path: str | None = None
        self._file: Any | None = None
        self._writer: csv.DictWriter[str] | None = None
        self._lock = threading.Lock()

    def start_run(
        self,
        *,
        run_id: str,
        profile_name: str,
        startat_seconds: float,
        total_seconds: float,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Create run files and write a start row."""
        if not self.enabled:
            return None

        with self._lock:
            self._close_unlocked()
            try:
                os.makedirs(self.output_dir, exist_ok=True)
                stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                profile_token = sanitize_for_filename(profile_name)
                run_token = sanitize_for_filename(run_id)[:8]
                basename = f"{stamp}-{profile_token}-{run_token}"
                csv_path = self.output_dir / f"{basename}.csv"
                meta_path = self.output_dir / f"{basename}.meta.json"

                self._file = csv_path.open("w", newline="", encoding="utf-8")
                self._writer = csv.DictWriter(
                    self._file,
                    FIRING_RECORD_COLUMNS,
                    extrasaction="ignore",
                )
                self._writer.writeheader()

                metadata_row = {
                    "schema": SCHEMA_VERSION,
                    "created_at": utc_iso(),
                    "run_id": run_id,
                    "profile": profile_name,
                    "startat_seconds": startat_seconds,
                    "total_seconds": total_seconds,
                    "columns": FIRING_RECORD_COLUMNS,
                    "metadata": metadata or {},
                }
                with meta_path.open("w", encoding="utf-8") as meta_file:
                    json.dump(metadata_row, meta_file, ensure_ascii=False, indent=2)

                self.current_csv_path = str(csv_path)
                self.current_meta_path = str(meta_path)
                self._write_row_unlocked(
                    {
                        "row_type": "start",
                        "ts_utc": utc_iso(),
                        "run_id": run_id,
                        "profile": profile_name,
                        "runtime_s": startat_seconds,
                        "total_s": total_seconds,
                        "time_left_s": max(0.0, total_seconds - startat_seconds),
                        "startat_s": startat_seconds,
                        "notes": SCHEMA_VERSION,
                    }
                )
                log.info("firing record started: %s", csv_path)
                return self.current_csv_path
            except Exception as exc:
                log.error("failed to start firing record: %s", exc)
                self._close_unlocked()
                return None

    def write_sample(self, row: dict[str, Any]) -> None:
        """Write one cycle sample row if recording is active."""
        if not self.enabled:
            return
        with self._lock:
            if not self._writer:
                return
            try:
                if "row_type" not in row:
                    row["row_type"] = "sample"
                if "ts_utc" not in row:
                    row["ts_utc"] = utc_iso()
                self._write_row_unlocked(row)
            except Exception as exc:
                log.error("failed writing firing sample: %s", exc)

    def end_run(self, reason: str, summary: dict[str, Any]) -> None:
        """Write an end-of-run row and summary sidecar JSON."""
        if not self.enabled:
            return
        with self._lock:
            if not self._writer:
                return
            try:
                self._write_row_unlocked(
                    {
                        "row_type": "end",
                        "ts_utc": utc_iso(),
                        "run_id": summary.get("run_id"),
                        "profile": summary.get("profile"),
                        "reason": reason,
                        "runtime_s": summary.get("runtime_seconds"),
                        "total_s": summary.get("runtime_seconds"),
                        "time_left_s": 0,
                        "runtime_hours": summary.get("runtime_hours"),
                        "cost": summary.get("cost"),
                        "max_temp": summary.get("max_temp"),
                        "max_target": summary.get("max_target"),
                        "peak_profile_target": summary.get("peak_profile_target"),
                        "max_temp_gap_to_peak_target": summary.get("max_temp_gap_to_peak_target"),
                        "within_5deg": summary.get("within_5deg_pct"),
                        "switch_count_run": summary.get("switch_count"),
                        "switches_per_hour_run": summary.get("switches_per_hour"),
                        "overshoot_max_run": summary.get("overshoot_max"),
                        "heat_duty_pct": summary.get("heat_duty_pct"),
                        "high_temp_seconds": summary.get("high_temp_seconds"),
                        "high_temp_duty_pct": summary.get("high_temp_duty_pct"),
                        "high_temp_mae": summary.get("high_temp_mae"),
                        "catching_up_seconds": summary.get("catching_up_seconds"),
                        "catching_up_pct": summary.get("catching_up_pct"),
                        "sensor_error_pct": summary.get("sensor_error_rate_5m"),
                        "completed": summary.get("completed"),
                        "notes": "run_summary",
                    }
                )
                if self.current_csv_path:
                    summary_path = Path(self.current_csv_path).with_suffix(".summary.json")
                    with summary_path.open("w", encoding="utf-8") as summary_file:
                        json.dump(summary, summary_file, ensure_ascii=False, indent=2)
            except Exception as exc:
                log.error("failed to finalize firing record: %s", exc)

    def close(self) -> None:
        """Close active run CSV handle."""
        with self._lock:
            self._close_unlocked()

    def _write_row_unlocked(self, row: dict[str, Any]) -> None:
        if not self._writer:
            return
        normalized = dict.fromkeys(FIRING_RECORD_COLUMNS, "")
        for key, value in row.items():
            if key not in normalized:
                continue
            if value is None:
                normalized[key] = ""
            elif isinstance(value, dict | list | tuple):
                normalized[key] = json.dumps(value, ensure_ascii=False)
            else:
                normalized[key] = value
        self._writer.writerow(normalized)
        if self.flush_each_row and self._file:
            self._file.flush()

    def _close_unlocked(self) -> None:
        if self._file:
            with suppress(Exception):
                self._file.close()
        self._file = None
        self._writer = None
