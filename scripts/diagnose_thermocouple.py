#!/usr/bin/env python3
"""Low-level MAX31856 diagnostic utility."""

from __future__ import annotations

import datetime
import time

import adafruit_bitbangio as bitbangio
import config
import digitalio
from digitalio import DigitalInOut

from thekilngod.thermocouple_diagnostics import (
    Max31856Snapshot,
    classify_max31856_snapshot,
    summarize_findings,
)

try:
    import board
except NotImplementedError:
    print("not running a recognized blinka board, exiting...")
    raise SystemExit(1)


REGISTER_COUNT = 16


def build_spi():
    """Create the configured SPI object and return it with a mode label."""
    if (
        hasattr(config, "spi_sclk")
        and hasattr(config, "spi_mosi")
        and hasattr(config, "spi_miso")
    ):
        spi = bitbangio.SPI(config.spi_sclk, config.spi_mosi, config.spi_miso)
        mode = "software"
    else:
        spi = board.SPI()
        mode = "hardware"
    return spi, mode


def format_temp(temp_c):
    """Format a Celsius reading in the configured display scale."""
    if temp_c is None:
        return "n/a"
    value = temp_c
    scale = "C"
    if config.temp_scale.lower() == "f":
        value = temp_c * (9 / 5) + 32
        scale = "F"
    return f"{value:0.2f}{scale}"


def read_register_block(spi, cs, start_register=0x00, length=REGISTER_COUNT):
    """Read a block of MAX31856 registers over raw SPI."""
    tx = bytearray(length + 1)
    rx = bytearray(length + 1)
    tx[0] = start_register & 0x7F

    while not spi.try_lock():
        time.sleep(0.001)
    try:
        spi.configure(baudrate=500000, phase=1, polarity=0)
        cs.value = False
        spi.write_readinto(tx, rx)
        cs.value = True
    finally:
        spi.unlock()

    return tuple(rx[1:])


def print_config(mode):
    """Print the active configuration so wiring can be checked quickly."""
    print(f"board: {board.board_id}")
    print(f"thermocouple: {'MAX31856' if config.max31856 else 'MAX31855'}")
    print(f"SPI mode: {mode}")
    print(f"Degrees displayed in {config.temp_scale}")
    print(f"CS pin: {getattr(config, 'spi_cs', 'n/a')}")
    if mode == "software":
        print(f"SCLK pin: {config.spi_sclk}")
        print(f"MOSI pin: {config.spi_mosi}")
        print(f"MISO pin: {config.spi_miso}")


def main():
    """Run repeated interpreted and raw diagnostics for MAX31856."""
    if not config.max31856:
        print("This diagnostic is currently focused on MAX31856 setups.")
        return 1

    import adafruit_max31856

    spi, mode = build_spi()
    cs = DigitalInOut(config.spi_cs)
    cs.switch_to_output(value=True)
    sensor = adafruit_max31856.MAX31856(spi, cs, thermocouple_type=config.thermocouple_type)

    print_config(mode)
    print("Reading raw registers 0x00-0x0F plus interpreted temperatures.\n")

    try:
        while True:
            time.sleep(1)
            registers = read_register_block(spi, cs)
            probe_c = sensor.temperature
            ref_c = sensor.reference_temperature
            fault = dict(sensor.fault)
            snapshot = Max31856Snapshot(
                registers=registers,
                probe_temp_c=probe_c,
                reference_temp_c=ref_c,
                fault=fault,
            )
            findings = classify_max31856_snapshot(snapshot)
            register_text = " ".join(f"{value:02X}" for value in registers)
            print(
                f"{datetime.datetime.now()} "
                f"probe={format_temp(probe_c)} "
                f"ref={format_temp(ref_c)} "
                f"fault={fault}"
            )
            print(f"  regs[00:0F]={register_text}")
            if findings:
                print(f"  diagnosis: {summarize_findings(findings)}")
                print(f"  finding_ids: {', '.join(findings)}")
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        if isinstance(cs, digitalio.DigitalInOut):
            cs.deinit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
