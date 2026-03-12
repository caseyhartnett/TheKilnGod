"""Unit tests for oven runtime reason text helpers."""

from __future__ import annotations

from thekilngod.oven import describe_run_reason


def test_describe_run_reason_marks_schedule_complete() -> None:
    info = describe_run_reason("schedule_complete")

    assert info["reason_kind"] == "complete"
    assert info["reason_text"] == "Reached the end of the firing plan"


def test_describe_run_reason_formats_emergency_temperature() -> None:
    info = describe_run_reason(
        "emergency_temp_too_high",
        temperature=2364,
        temp_limit=2350,
    )

    assert info["reason_kind"] == "error"
    assert info["reason_text"] == "Emergency stop: 2364F exceeded limit 2350F"


def test_describe_run_reason_formats_sensor_error_rate() -> None:
    info = describe_run_reason(
        "emergency_tc_error_rate",
        sensor_error_pct=42,
        sensor_error_limit_pct=30,
    )

    assert info["reason_kind"] == "error"
    assert info["reason_text"] == "Emergency stop: thermocouple errors 42% exceeded 30%"


def test_describe_run_reason_marks_legacy_manual_stop() -> None:
    info = describe_run_reason("manual_stop_ws")

    assert info["reason_kind"] == "stopped"
    assert info["reason_text"] == "Stopped manually from the legacy UI"
