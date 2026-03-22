#!/usr/bin/env python
import datetime
import sys
import time

import config


def format_temp(temp_c):
    value = temp_c
    scale = "C"
    if config.temp_scale == "f":
        value = temp_c * (9 / 5) + 32
        scale = "F"
    return f"{value:0.2f}{scale}"


# ---------------------------------------------------------------------------
# spidev path — kernel hardware SPI, no userspace GPIO required
# ---------------------------------------------------------------------------
if getattr(config, "use_spidev", False):
    import spidev

    bus    = int(getattr(config, "spidev_bus",    0))
    device = int(getattr(config, "spidev_device", 0))

    spi = spidev.SpiDev()
    spi.open(bus, device)
    spi.max_speed_hz = 500000
    spi.mode         = 1
    spi.lsbfirst     = False

    print(f"Hardware SPI via spidev (/dev/spidev{bus}.{device})")
    print(f"  SCK  → BCM 11 (pin 23)")
    print(f"  MOSI → BCM 10 (pin 19)  [MAX31856 SDI]")
    print(f"  MISO → BCM  9 (pin 21)  [MAX31856 DO]")
    print(f"  CE0  → BCM  8 (pin 24)  [MAX31856 CS]")
    print(f"thermocouple: MAX31856 (spidev)")
    print(f"Degrees displayed in {config.temp_scale}\n")

    def _read(start_reg, count):
        data = spi.xfer2([start_reg & 0x7F] + [0x00] * count)
        return data[1:]

    def _write(reg, value):
        spi.xfer2([0x80 | reg, value])

    # initialise: auto-convert, open-circuit detection, correct noise filter
    cr0 = 0x80 | 0x10  # CMODE | OCFAULT0
    if getattr(config, "ac_freq_50hz", False):
        cr0 |= 0x01
    _write(0x00, cr0)
    tc_type = getattr(config, "thermocouple_type", None)
    _write(0x01, (int(tc_type) & 0x07) if tc_type is not None else 0x03)
    _write(0x02, 0x00)
    time.sleep(0.2)  # let first auto-convert complete

    try:
        while True:
            time.sleep(1)
            try:
                regs = _read(0x00, 16)
                reg_hex = " ".join(f"{b:02X}" for b in regs)

                # probe temperature: LTCBH/M/L registers 0x0C–0x0E
                raw_probe = (regs[0x0C] << 16 | regs[0x0D] << 8 | regs[0x0E]) >> 5
                if raw_probe & 0x40000:
                    raw_probe -= 0x80000
                probe_c = raw_probe * 0.0078125

                # cold junction: CJTH/L registers 0x0A–0x0B
                raw_cj = (regs[0x0A] << 8 | regs[0x0B]) >> 2
                if raw_cj & 0x2000:
                    raw_cj -= 0x4000
                ref_c = raw_cj * 0.015625

                sr = regs[0x0F]
                fault = {
                    "cj_range": bool(sr & 0x80), "tc_range": bool(sr & 0x40),
                    "cj_high":  bool(sr & 0x20), "cj_low":   bool(sr & 0x10),
                    "tc_high":  bool(sr & 0x08), "tc_low":   bool(sr & 0x04),
                    "voltage":  bool(sr & 0x02), "open_tc":  bool(sr & 0x01),
                }

                print(
                    f"{datetime.datetime.now()} "
                    f"probe={format_temp(probe_c)} "
                    f"ref={format_temp(ref_c)} "
                    f"fault={fault}"
                )
                print(f"  regs[00:0F]={reg_hex}")
                if probe_c == 0.0 and ref_c == 0.0 and not any(fault.values()):
                    print(
                        "  note: all zeros with no faults — "
                        "check wiring or run: thekilngod test thermocouple-diagnose"
                    )
            except Exception as error:
                print("error:", error)
    except KeyboardInterrupt:
        spi.close()
        print("\nstopped")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Blinka path — software or hardware SPI via adafruit libraries
# ---------------------------------------------------------------------------
import adafruit_bitbangio as bitbangio
from digitalio import DigitalInOut

try:
    import board
except NotImplementedError:
    print("not running a recognized blinka board, exiting...")
    sys.exit()

spi = None
if (
    hasattr(config, "spi_sclk")
    and hasattr(config, "spi_mosi")
    and hasattr(config, "spi_miso")
):
    spi = bitbangio.SPI(config.spi_sclk, config.spi_mosi, config.spi_miso)
    print("Software SPI selected for reading thermocouple")
    print("SPI configured as:\n")
    print("    config.spi_sclk = %s BCM pin" % (config.spi_sclk))
    print("    config.spi_mosi = %s BCM pin" % (config.spi_mosi))
    print("    config.spi_miso = %s BCM pin" % (config.spi_miso))
    print("    config.spi_cs   = %s BCM pin\n" % (config.spi_cs))
else:
    spi = board.SPI()
    print("Hardware SPI selected for reading thermocouple")

cs = DigitalInOut(config.spi_cs)
cs.switch_to_output(value=True)
sensor = None

print("\nboard: %s" % (board.board_id))
if config.max31855:
    import adafruit_max31855
    print("thermocouple: adafruit max31855")
    sensor = adafruit_max31855.MAX31855(spi, cs)
if config.max31856:
    import adafruit_max31856
    print("thermocouple: adafruit max31856")
    sensor = adafruit_max31856.MAX31856(spi, cs)

print("Degrees displayed in %s\n" % (config.temp_scale))

try:
    while True:
        time.sleep(1)
        try:
            temp_c = sensor.temperature
            if config.max31856:
                ref_c = sensor.reference_temperature
                fault = sensor.fault
                print(
                    f"{datetime.datetime.now()} "
                    f"probe={format_temp(temp_c)} "
                    f"ref={format_temp(ref_c)} "
                    f"fault={fault}"
                )
                if temp_c == 0.0 and ref_c == 0.0 and not any(fault.values()):
                    print(
                        "  note: both readings are 0.0C with no faults; "
                        "this often means SPI comms are returning all zeros"
                    )
            else:
                print("%s %s" % (datetime.datetime.now(), format_temp(temp_c)))
        except Exception as error:
            print("error: ", error)
except KeyboardInterrupt:
    print("\nstopped")
