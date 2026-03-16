"""Helpers for diagnosing MAX31856 thermocouple communication failures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Max31856Snapshot:
    """One interpreted and raw observation from the thermocouple board."""

    registers: tuple[int, ...]
    probe_temp_c: float | None
    reference_temp_c: float | None
    fault: dict[str, bool]


def classify_max31856_snapshot(snapshot: Max31856Snapshot) -> list[str]:
    """Return likely diagnostic findings for one MAX31856 sample."""
    findings: list[str] = []
    registers = snapshot.registers

    if registers and all(value == 0x00 for value in registers):
        findings.append("raw_registers_all_zero")
    elif registers and all(value == 0xFF for value in registers):
        findings.append("raw_registers_all_ones")

    if (
        snapshot.probe_temp_c == 0.0
        and snapshot.reference_temp_c == 0.0
        and not any(snapshot.fault.values())
    ):
        findings.append("zero_temps_without_faults")

    if registers and len(set(registers)) == 1 and registers[0] not in (0x00, 0xFF):
        findings.append("raw_registers_suspiciously_constant")

    return findings


def summarize_findings(findings: list[str]) -> str:
    """Translate raw finding identifiers into a concise operator summary."""
    if "raw_registers_all_zero" in findings and "zero_temps_without_faults" in findings:
        return (
            "SPI reads are returning all zero bytes. This usually means the MAX31856 "
            "is powered incorrectly, not driving SDO, or SDO/CLK/CS is not reaching the Pi."
        )
    if "raw_registers_all_ones" in findings:
        return (
            "SPI reads are returning all 0xFF bytes. This often means the data line is floating "
            "high or the chip-select/data wiring is wrong."
        )
    if "zero_temps_without_faults" in findings:
        return (
            "The library sees 0.0C for both probe and reference with no faults. That is not a "
            "normal thermocouple failure and usually points to bad SPI communication."
        )
    if "raw_registers_suspiciously_constant" in findings:
        return (
            "Raw register bytes are repeating the same value, which is unusual for a live MAX31856 "
            "and suggests a stuck or miswired SPI path."
        )
    return "No obvious SPI signature was detected in this sample."
