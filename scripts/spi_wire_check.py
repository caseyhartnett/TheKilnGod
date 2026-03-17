#!/usr/bin/env python3
"""
SPI wiring diagnostic — tests GPIO and SPI communication independently
of the MAX31856 driver to isolate where the failure is.

Usage:
    python3 scripts/spi_wire_check.py

Run this on the Pi with the MAX31856 wired up.
"""

import sys
import time

try:
    import board
    import digitalio
    import adafruit_bitbangio as bitbangio
except Exception as e:
    print(f"Failed to import board libraries: {e}")
    sys.exit(1)

import config


def test_gpio_toggling():
    """Verify each SPI GPIO can be driven high/low as a basic output."""
    print("=" * 60)
    print("TEST 1: GPIO output toggle (verifies pins are accessible)")
    print("=" * 60)
    pins = {
        "SCLK": getattr(config, "spi_sclk", None),
        "MOSI": getattr(config, "spi_mosi", None),
        "CS":   getattr(config, "spi_cs", None),
    }
    all_ok = True
    for name, pin in pins.items():
        if pin is None:
            print(f"  {name}: not configured, skipping")
            continue
        try:
            dio = digitalio.DigitalInOut(pin)
            dio.switch_to_output(value=False)
            v_low = dio.value
            dio.value = True
            time.sleep(0.01)
            v_high = dio.value
            dio.deinit()
            ok = (v_low == False and v_high == True)
            status = "OK" if ok else "FAIL"
            print(f"  {name} (pin {pin}): low={v_low} high={v_high} [{status}]")
            if not ok:
                all_ok = False
        except Exception as e:
            print(f"  {name} (pin {pin}): ERROR - {e}")
            all_ok = False

    miso_pin = getattr(config, "spi_miso", None)
    if miso_pin:
        try:
            dio = digitalio.DigitalInOut(miso_pin)
            dio.switch_to_input()
            val = dio.value
            dio.deinit()
            print(f"  MISO (pin {miso_pin}): reads {'HIGH' if val else 'LOW'} as input")
            if not val:
                print("    ^ MISO is LOW — if MAX31856 is powered and CS is high,")
                print("      SDO should be high-impedance (often pulled high).")
                print("      LOW suggests: chip not powered, wrong pin, or shorted to GND.")
        except Exception as e:
            print(f"  MISO (pin {miso_pin}): ERROR - {e}")
            all_ok = False

    return all_ok


def test_miso_responds_to_cs():
    """Toggle CS and see if MISO changes — a sign the MAX31856 is alive."""
    print()
    print("=" * 60)
    print("TEST 2: Does MISO respond when CS is asserted?")
    print("=" * 60)
    miso_pin = getattr(config, "spi_miso", None)
    cs_pin = getattr(config, "spi_cs", None)
    if not miso_pin or not cs_pin:
        print("  MISO or CS not configured, skipping")
        return False

    try:
        miso = digitalio.DigitalInOut(miso_pin)
        miso.switch_to_input()
        cs = digitalio.DigitalInOut(cs_pin)
        cs.switch_to_output(value=True)

        cs.value = True
        time.sleep(0.01)
        miso_cs_high = miso.value

        cs.value = False
        time.sleep(0.01)
        miso_cs_low = miso.value

        cs.value = True
        time.sleep(0.01)

        cs.deinit()
        miso.deinit()

        print(f"  MISO when CS=HIGH (deselected): {'HIGH' if miso_cs_high else 'LOW'}")
        print(f"  MISO when CS=LOW  (selected):   {'HIGH' if miso_cs_low else 'LOW'}")
        if miso_cs_high == miso_cs_low:
            print("  ^ MISO did not change — MAX31856 may not be responding.")
            print("    Check: power (Vin/3.3V and GND), CS wiring, SDO wiring.")
            return False
        else:
            print("  ^ MISO changed — MAX31856 is responding to chip-select!")
            return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def test_spi_loopback():
    """
    Software SPI loopback: connect MOSI directly to MISO (remove MAX31856).
    If this reads back the sent data, the bit-bang SPI is working.
    """
    print()
    print("=" * 60)
    print("TEST 3: SPI loopback (ONLY run with MOSI jumpered to MISO)")
    print("=" * 60)
    print("  This test checks if the software SPI bit-bang itself works.")
    print("  To run: disconnect the MAX31856, connect a jumper wire")
    print("  directly from MOSI (BCM {}) to MISO (BCM {}).".format(
        getattr(config, "spi_mosi", "?"),
        getattr(config, "spi_miso", "?"),
    ))

    answer = input("  Is MOSI jumpered directly to MISO? (y/n): ").strip().lower()
    if answer != "y":
        print("  Skipping loopback test.")
        return None

    sclk = getattr(config, "spi_sclk", None)
    mosi = getattr(config, "spi_mosi", None)
    miso = getattr(config, "spi_miso", None)
    if not all([sclk, mosi, miso]):
        print("  Software SPI pins not configured, cannot run loopback.")
        return False

    try:
        spi = bitbangio.SPI(sclk, mosi, miso)
        while not spi.try_lock():
            time.sleep(0.001)

        spi.configure(baudrate=500000, polarity=0, phase=1)
        tx = bytearray([0xA5, 0x5A, 0xFF, 0x01])
        rx = bytearray(len(tx))
        spi.write_readinto(tx, rx)
        spi.unlock()
        spi.deinit()

        print(f"  Sent:     {' '.join(f'{b:02X}' for b in tx)}")
        print(f"  Received: {' '.join(f'{b:02X}' for b in rx)}")

        if tx == rx:
            print("  LOOPBACK OK — software SPI bit-bang is working correctly.")
            return True
        elif all(b == 0 for b in rx):
            print("  All zeros received — MISO line is stuck low even with loopback.")
            print("  Possible causes:")
            print("    - Jumper wire not making contact")
            print("    - MISO pin claimed by kernel SPI driver (check /boot/config.txt)")
            print("    - Wrong physical pin")
            return False
        else:
            print("  Partial data — SPI is partially working but data is corrupted.")
            print("  Could be a timing issue or loose connection.")
            return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def test_raw_register_read():
    """Try a raw SPI register read without the Adafruit MAX31856 driver."""
    print()
    print("=" * 60)
    print("TEST 4: Raw SPI register read from MAX31856")
    print("=" * 60)

    sclk = getattr(config, "spi_sclk", None)
    mosi = getattr(config, "spi_mosi", None)
    miso = getattr(config, "spi_miso", None)
    cs_pin = getattr(config, "spi_cs", None)

    if not all([sclk, mosi, miso, cs_pin]):
        print("  Pins not fully configured, trying hardware SPI...")
        try:
            spi = board.SPI()
        except Exception as e:
            print(f"  Hardware SPI also failed: {e}")
            return False
    else:
        spi = bitbangio.SPI(sclk, mosi, miso)

    cs = digitalio.DigitalInOut(cs_pin)
    cs.switch_to_output(value=True)

    while not spi.try_lock():
        time.sleep(0.001)
    try:
        spi.configure(baudrate=500000, polarity=0, phase=1)

        # Read all 16 registers (0x00-0x0F)
        tx = bytearray(17)
        rx = bytearray(17)
        tx[0] = 0x00  # start at register 0, bit 7 clear = read

        cs.value = False
        spi.write_readinto(tx, rx)
        cs.value = True

        regs = rx[1:]
        reg_hex = " ".join(f"{b:02X}" for b in regs)
        print(f"  Raw registers [00-0F]: {reg_hex}")

        if all(b == 0x00 for b in regs):
            print("  ALL ZEROS — no communication with MAX31856.")
            print()
            print("  This confirms the problem is at the physical/electrical level:")
            print("    1. Is the MAX31856 getting power? Measure Vin (should be 3.3V or 5V)")
            print("    2. Is GND connected between Pi and MAX31856?")
            print("    3. Is SDO on MAX31856 connected to MISO on Pi (BCM {})?".format(miso))
            print("    4. Is SDI on MAX31856 connected to MOSI on Pi (BCM {})?".format(mosi))
            print("    5. Is CS on MAX31856 connected to CS on Pi (BCM {})?".format(cs_pin))
            print("    6. Is SCK on MAX31856 connected to SCLK on Pi (BCM {})?".format(sclk))
            return False
        elif all(b == 0xFF for b in regs):
            print("  ALL 0xFF — MISO line is floating high (no chip driving it).")
            print("  MAX31856 is not responding. Check CS and power wiring.")
            return False
        else:
            print("  Got non-trivial data — MAX31856 IS communicating!")
            cr0 = regs[0]
            print(f"  CR0 (config reg 0) = 0x{cr0:02X}")
            print(f"    Expected after reset: 0x00 or 0x10")
            cj_raw = (regs[0x0A] << 8 | regs[0x0B]) >> 2
            cj_c = cj_raw * 0.015625
            print(f"  Cold junction raw = {cj_c:.2f}°C (should be ~room temp)")
            return True
    finally:
        spi.unlock()
        cs.deinit()


def check_boot_config():
    """Check if hardware SPI overlay might be claiming GPIO pins."""
    print()
    print("=" * 60)
    print("TEST 5: Check for SPI kernel overlay conflicts")
    print("=" * 60)
    try:
        with open("/boot/config.txt", "r") as f:
            content = f.read()
    except FileNotFoundError:
        try:
            with open("/boot/firmware/config.txt", "r") as f:
                content = f.read()
        except FileNotFoundError:
            print("  Could not find /boot/config.txt or /boot/firmware/config.txt")
            return

    spi_enabled = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "dtparam=spi=on" in stripped:
            spi_enabled = True

    if spi_enabled:
        print("  WARNING: dtparam=spi=on is ENABLED in boot config!")
        print("  This means the kernel SPI driver claims BCM pins 9, 10, 11.")
        print()
        print("  Your software SPI uses BCM 10 for MOSI — this pin may be")
        print("  unavailable for GPIO bit-banging because the kernel owns it.")
        print()
        print("  Options:")
        print("    a) Disable hardware SPI: comment out dtparam=spi=on")
        print("       (then reboot)")
        print("    b) Change MOSI to a different BCM pin (not 9, 10, or 11)")
        print("    c) Use hardware SPI instead (remove spi_sclk/mosi/miso from config)")
    else:
        print("  dtparam=spi=on is NOT enabled — no kernel SPI conflict detected.")

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "dtoverlay" in stripped and "spi" in stripped.lower():
            print(f"  NOTE: found SPI-related overlay: {stripped}")


def main():
    print("TheKilnGod SPI Wiring Diagnostic")
    print(f"Board: {board.board_id}")
    print(f"SCLK={getattr(config, 'spi_sclk', 'N/A')}, "
          f"MOSI={getattr(config, 'spi_mosi', 'N/A')}, "
          f"MISO={getattr(config, 'spi_miso', 'N/A')}, "
          f"CS={getattr(config, 'spi_cs', 'N/A')}")
    print()

    check_boot_config()
    test_gpio_toggling()
    test_miso_responds_to_cs()
    test_raw_register_read()
    test_spi_loopback()


if __name__ == "__main__":
    main()
