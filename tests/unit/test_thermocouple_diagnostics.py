"""Unit tests for MAX31856 diagnostic helpers."""

from thekilngod.thermocouple_diagnostics import (
    Max31856Snapshot,
    classify_max31856_snapshot,
    summarize_findings,
)


def test_classify_all_zero_registers_and_zero_temps() -> None:
    snapshot = Max31856Snapshot(
        registers=(0x00,) * 16,
        probe_temp_c=0.0,
        reference_temp_c=0.0,
        fault={"open_tc": False, "voltage": False},
    )

    findings = classify_max31856_snapshot(snapshot)

    assert "raw_registers_all_zero" in findings
    assert "zero_temps_without_faults" in findings
    assert "all zero bytes" in summarize_findings(findings)


def test_classify_all_ones_registers() -> None:
    snapshot = Max31856Snapshot(
        registers=(0xFF,) * 16,
        probe_temp_c=None,
        reference_temp_c=None,
        fault={"open_tc": False},
    )

    findings = classify_max31856_snapshot(snapshot)

    assert findings == ["raw_registers_all_ones"]
    assert "0xFF" in summarize_findings(findings)
