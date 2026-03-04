#!/usr/bin/env python3
"""Quick power-sensor confirmation test using a fixed heater pattern.

Pattern:
  ON  for 10 seconds
  OFF for 10 seconds
  ON  for 10 seconds
"""

from __future__ import annotations

import argparse
import datetime
import statistics
import time

import config
import digitalio

from thekilngod.power_sensor import Pzem004tPowerSensor


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.mean(values))


def main() -> int:
    parser = argparse.ArgumentParser(description="Test power sensor with ON/OFF/ON heater pulse.")
    parser.add_argument("--on-seconds", type=float, default=10.0, help="Seconds for each ON phase")
    parser.add_argument("--off-seconds", type=float, default=10.0, help="Seconds for OFF phase")
    parser.add_argument(
        "--sample-seconds",
        type=float,
        default=0.5,
        help="Sample interval while collecting power/current data",
    )
    parser.add_argument(
        "--current-threshold",
        type=float,
        default=float(getattr(config, "power_sensor_current_threshold_amps", 0.25)),
        help="Current threshold (A) used for pass/fail signal check",
    )
    parser.add_argument(
        "--port",
        type=str,
        default=str(getattr(config, "power_sensor_port", "/dev/ttyUSB0")),
        help="Serial port for PZEM-004T",
    )
    parser.add_argument(
        "--address",
        type=int,
        default=int(getattr(config, "power_sensor_address", 1)),
        help="PZEM modbus address",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=int(getattr(config, "power_sensor_baudrate", 9600)),
        help="PZEM UART baudrate",
    )
    args = parser.parse_args()

    heater = digitalio.DigitalInOut(config.gpio_heat)
    heater.direction = digitalio.Direction.OUTPUT
    off = bool(config.gpio_heat_invert)
    on = not off

    sensor = Pzem004tPowerSensor(
        port=args.port,
        address=args.address,
        baudrate=args.baudrate,
        poll_interval=max(0.2, min(args.sample_seconds, 1.0)),
        timeout=float(getattr(config, "power_sensor_timeout", 0.4)),
        stale_seconds=float(getattr(config, "power_sensor_stale_seconds", 10.0)),
    )
    sensor.start()

    print("")
    print("Power Sensor Test (ON/OFF/ON)")
    print(f"  Start time: {datetime.datetime.now().isoformat(sep=' ', timespec='seconds')}")
    print(f"  Heater pin: {config.gpio_heat} (invert={config.gpio_heat_invert})")
    print(f"  Sensor: PZEM-004T on {args.port} @ {args.baudrate}, addr={args.address}")
    print(f"  Pattern: ON {args.on_seconds}s -> OFF {args.off_seconds}s -> ON {args.on_seconds}s")
    print("")

    phases = [
        ("ON-1", True, float(args.on_seconds)),
        ("OFF", False, float(args.off_seconds)),
        ("ON-2", True, float(args.on_seconds)),
    ]
    phase_currents: dict[str, list[float]] = {name: [] for name, _, _ in phases}
    phase_powers: dict[str, list[float]] = {name: [] for name, _, _ in phases}

    try:
        heater.value = off
        time.sleep(0.2)
        for name, heat_enabled, duration in phases:
            heater.value = on if heat_enabled else off
            phase_end = time.time() + duration
            while time.time() < phase_end:
                snap = sensor.snapshot()
                current = snap.get("current")
                power = snap.get("power")
                if current is not None:
                    phase_currents[name].append(float(current))
                if power is not None:
                    phase_powers[name].append(float(power))
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                current_txt = "--" if current is None else f"{float(current):.3f}A"
                power_txt = "--" if power is None else f"{float(power):.1f}W"
                print(f"{ts} {name:4} heat={'ON ' if heat_enabled else 'OFF'} current={current_txt:>8} power={power_txt:>8}")
                time.sleep(max(0.1, float(args.sample_seconds)))
    finally:
        heater.value = off
        sensor.stop()
        sensor.join(timeout=2.0)

    on1_avg = _mean(phase_currents["ON-1"])
    off_avg = _mean(phase_currents["OFF"])
    on2_avg = _mean(phase_currents["ON-2"])
    on_avg = _mean(phase_currents["ON-1"] + phase_currents["ON-2"])
    off_power_avg = _mean(phase_powers["OFF"])
    on_power_avg = _mean(phase_powers["ON-1"] + phase_powers["ON-2"])

    print("")
    print("Summary")
    print(f"  Avg current ON-1: {on1_avg:.3f}A")
    print(f"  Avg current OFF : {off_avg:.3f}A")
    print(f"  Avg current ON-2: {on2_avg:.3f}A")
    print(f"  Avg power   ON  : {on_power_avg:.1f}W")
    print(f"  Avg power   OFF : {off_power_avg:.1f}W")

    pass_on = on_avg > float(args.current_threshold)
    pass_off = off_avg <= float(args.current_threshold)
    phase_on_samples = len(phase_currents["ON-1"]) + len(phase_currents["ON-2"])
    phase_off_samples = len(phase_currents["OFF"])
    if phase_on_samples == 0 or phase_off_samples == 0:
        print("  Result: FAIL (insufficient sensor samples collected)")
        return 2
    if pass_on and pass_off:
        print(
            "  Result: PASS (current follows expected ON/OFF/ON signal "
            f"using threshold {float(args.current_threshold):.3f}A)"
        )
        return 0

    print(
        "  Result: CHECK FAILED "
        f"(expected ON > {float(args.current_threshold):.3f}A and OFF <= threshold)"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
