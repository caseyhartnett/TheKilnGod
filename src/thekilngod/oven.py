"""Kiln control runtime model, including real and simulated ovens.

This module owns the control-loop state machine, telemetry aggregation, and
profile interpolation behavior used by the web/API layer.
"""

from __future__ import annotations

import datetime
import json
import logging
import math
import os
import statistics
import threading
import time
import uuid
from collections import deque
from collections.abc import Sequence
from typing import Any

import adafruit_bitbangio as bitbangio
import config
import digitalio

from .firing_record import FiringRecordWriter
from .power_sensor import NullPowerSensor, Pzem004tPowerSensor
from .telemetry_math import avg, bool_pct

log = logging.getLogger(__name__)


class DupFilter:
    """Filter duplicate log messages to reduce repeated noisy output."""

    def __init__(self):
        self.msgs = set()

    def filter(self, record: logging.LogRecord) -> bool:
        rv = record.msg not in self.msgs
        self.msgs.add(record.msg)
        return rv


class Duplogger:
    """Wrapper that provides a duplicate-filtered logger instance."""

    def __init__(self):
        self.log = logging.getLogger("%s.dupfree" % (__name__))
        dup_filter = DupFilter()
        self.log.addFilter(dup_filter)

    def logref(self) -> logging.Logger:
        return self.log


duplog = Duplogger().logref()


def _format_temp_with_scale(value: float | None) -> str | None:
    """Return a compact temperature string such as `2232F`."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    scale = str(getattr(config, "temp_scale", "f")).upper()
    return f"{numeric:.0f}{scale}"


def describe_run_reason(
    reason: str | None,
    *,
    temperature: float | None = None,
    temp_limit: float | None = None,
    sensor_error_pct: float | None = None,
    sensor_error_limit_pct: float | None = None,
) -> dict[str, str]:
    """Translate a raw stop reason into a concise UI-ready summary."""
    raw_reason = str(reason or "unknown").strip() or "unknown"
    reason_key = raw_reason.lower()
    temp_text = _format_temp_with_scale(temperature)
    limit_text = _format_temp_with_scale(temp_limit)

    if reason_key == "schedule_complete":
        return {
            "reason": raw_reason,
            "reason_kind": "complete",
            "reason_text": "Reached the end of the firing plan",
        }

    if reason_key in {"manual_stop", "manual_stop_http"}:
        return {
            "reason": raw_reason,
            "reason_kind": "stopped",
            "reason_text": "Stopped manually from the UI or API",
        }

    if reason_key == "manual_stop_ws":
        return {
            "reason": raw_reason,
            "reason_kind": "stopped",
            "reason_text": "Stopped manually from the legacy UI",
        }

    if reason_key == "emergency_temp_too_high":
        text = "Emergency stop: measured temperature exceeded the safety limit"
        if temp_text and limit_text:
            text = f"Emergency stop: {temp_text} exceeded limit {limit_text}"
        return {
            "reason": raw_reason,
            "reason_kind": "error",
            "reason_text": text,
        }

    if reason_key == "emergency_tc_error_rate":
        text = "Emergency stop: thermocouple error rate exceeded the safety limit"
        if sensor_error_pct is not None and sensor_error_limit_pct is not None:
            text = (
                "Emergency stop: thermocouple errors "
                f"{float(sensor_error_pct):.0f}% exceeded {float(sensor_error_limit_pct):.0f}%"
            )
        return {
            "reason": raw_reason,
            "reason_kind": "error",
            "reason_text": text,
        }

    if reason_key.startswith("emergency"):
        return {
            "reason": raw_reason,
            "reason_kind": "error",
            "reason_text": raw_reason.replace("_", " ").capitalize(),
        }

    if "abort" in reason_key or "stop" in reason_key:
        return {
            "reason": raw_reason,
            "reason_kind": "stopped",
            "reason_text": raw_reason.replace("_", " ").capitalize(),
        }

    return {
        "reason": raw_reason,
        "reason_kind": "info",
        "reason_text": raw_reason.replace("_", " ").capitalize(),
    }


def decide_catchup_shadow_state(
    avg_error_confidence: float,
    rise_rate_trend: float,
    duty_cycle_confidence_pct: float,
    lagging_seconds: float,
    cusum_deg_seconds: float,
    holdoff_active: bool,
) -> str:
    """Return shadow supervisor state from pre-computed trend metrics."""
    if holdoff_active:
        return "holdoff"
    if (
        avg_error_confidence > float(getattr(config, "catchup_supervisor_error_threshold", 50.0))
        and duty_cycle_confidence_pct
        >= float(getattr(config, "catchup_supervisor_high_duty_threshold_pct", 90.0))
        and rise_rate_trend
        <= float(getattr(config, "catchup_supervisor_stall_rise_rate_deg_per_hour", 5.0))
        and lagging_seconds
        >= float(getattr(config, "catchup_supervisor_abort_persistence_seconds", 2400.0))
        and cusum_deg_seconds
        >= float(getattr(config, "catchup_supervisor_cusum_alarm_deg_seconds", 60000.0))
    ):
        return "would_abort"
    if avg_error_confidence > float(
        getattr(config, "catchup_supervisor_error_threshold", 50.0)
    ) and rise_rate_trend >= float(
        getattr(config, "catchup_supervisor_min_rise_rate_deg_per_hour", 20.0)
    ):
        return "would_extend"
    return "normal"


class Output:
    """This represents a GPIO output that controls a solid
    state relay to turn the kiln elements on and off.
    inputs
        config.gpio_heat
        config.gpio_heat_invert
    """

    def __init__(self) -> None:
        self.active = False
        self.heater = digitalio.DigitalInOut(config.gpio_heat)
        self.heater.direction = digitalio.Direction.OUTPUT
        self.off = config.gpio_heat_invert
        self.on = not self.off

    def heat(self, sleepfor: float) -> None:
        self.heater.value = self.on
        time.sleep(sleepfor)

    def cool(self, sleepfor: float) -> None:
        """no active cooling, so sleep"""
        self.heater.value = self.off
        time.sleep(sleepfor)


# wrapper for blinka board
class Board:
    """This represents a blinka board where this code
    runs.
    """

    def __init__(self) -> None:
        log.info("board: %s" % (self.name))
        self.temp_sensor.start()
        if getattr(self, "power_sensor", None):
            self.power_sensor.start()


class RealBoard(Board):
    """Each board has a thermocouple board attached to it.
    Any blinka board that supports SPI can be used. The
    board is automatically detected by blinka.
    """

    def __init__(self) -> None:
        self.name = None
        self.load_libs()
        self.temp_sensor = self.choose_tempsensor()
        self.power_sensor = self.choose_power_sensor()
        Board.__init__(self)

    def load_libs(self) -> None:
        import board

        self.name = board.board_id

    def choose_tempsensor(self) -> TempSensorReal | None:
        if config.max31855:
            return Max31855()
        if config.max31856:
            return Max31856()

    def choose_power_sensor(self) -> Pzem004tPowerSensor | NullPowerSensor:
        if not bool(getattr(config, "power_sensor_enabled", False)):
            return NullPowerSensor(reason="disabled")

        sensor_type = str(getattr(config, "power_sensor_type", "pzem004t")).strip().lower()
        if sensor_type != "pzem004t":
            log.warning("unknown power sensor type '%s'; disabling power sensor", sensor_type)
            return NullPowerSensor(reason="unknown sensor type")
        try:
            return Pzem004tPowerSensor(
                port=str(getattr(config, "power_sensor_port", "/dev/ttyUSB0")),
                baudrate=int(getattr(config, "power_sensor_baudrate", 9600)),
                address=int(getattr(config, "power_sensor_address", 1)),
                poll_interval=float(getattr(config, "power_sensor_poll_interval", 2.0)),
                timeout=float(getattr(config, "power_sensor_timeout", 0.4)),
                stale_seconds=float(getattr(config, "power_sensor_stale_seconds", 10.0)),
            )
        except Exception as exc:
            log.error("failed to initialize power sensor: %s", exc)
            return NullPowerSensor(reason="init failed")


class SimulatedBoard(Board):
    """Simulated board used during simulations.
    See config.simulate
    """

    def __init__(self) -> None:
        self.name = "simulated"
        self.temp_sensor = TempSensorSimulated()
        self.power_sensor = NullPowerSensor(reason="simulation")
        Board.__init__(self)


class TempSensor(threading.Thread):
    """Used by the Board class. Each Board must have
    a TempSensor.
    """

    def __init__(self) -> None:
        threading.Thread.__init__(self)
        self.daemon = True
        self.time_step = config.sensor_time_wait
        self.status = ThermocoupleTracker()


class TempSensorSimulated(TempSensor):
    """Simulates a temperature sensor"""

    def __init__(self) -> None:
        TempSensor.__init__(self)
        self.simulated_temperature = config.sim_t_env

    def temperature(self) -> float:
        return self.simulated_temperature


class TempSensorReal(TempSensor):
    """real temperature sensor that takes many measurements
    during the time_step
    inputs
        config.temperature_average_samples
    """

    def __init__(self) -> None:
        TempSensor.__init__(self)
        self.sleeptime = self.time_step / float(config.temperature_average_samples)
        self.temptracker = TempTracker()
        self.spi_setup()
        self.cs = digitalio.DigitalInOut(config.spi_cs)

    def spi_setup(self) -> None:
        if (
            hasattr(config, "spi_sclk")
            and hasattr(config, "spi_mosi")
            and hasattr(config, "spi_miso")
        ):
            self.spi = bitbangio.SPI(config.spi_sclk, config.spi_mosi, config.spi_miso)
            log.info("Software SPI selected for reading thermocouple")
        else:
            import board

            self.spi = board.SPI()
            log.info("Hardware SPI selected for reading thermocouple")

    def get_temperature(self) -> float | None:
        """read temp from tc and convert if needed"""
        try:
            temp = self.raw_temp()  # raw_temp provided by subclasses
            if config.temp_scale.lower() == "f":
                temp = (temp * 9 / 5) + 32
            self.status.good()
            return temp
        except ThermocoupleError as tce:
            if tce.ignore:
                log.error("Problem reading temp (ignored) %s" % (tce.message))
                self.status.good()
            else:
                log.error("Problem reading temp %s" % (tce.message))
                self.status.bad()
        return None

    def temperature(self) -> float:
        """average temp over a duty cycle"""
        return self.temptracker.get_avg_temp()

    def run(self) -> None:
        while True:
            temp = self.get_temperature()
            if temp is not None:  # Fixed: Changed from 'if temp:' to handle 0° as valid temperature
                self.temptracker.add(temp)
            time.sleep(self.sleeptime)


class TempTracker:
    """creates a sliding window of N temperatures per
    config.sensor_time_wait
    """

    def __init__(self) -> None:
        self.size = config.temperature_average_samples
        self.temps = [0 for i in range(self.size)]

    def add(self, temp: float) -> None:
        self.temps.append(temp)
        while len(self.temps) > self.size:
            del self.temps[0]

    def get_avg_temp(self, chop: int = 25) -> float:
        """
        take the median of the given values. this used to take an avg
        after getting rid of outliers. median works better.
        """
        return statistics.median(self.temps)


class ThermocoupleTracker:
    """Keeps sliding window to track successful/failed calls to get temp
    over the last two duty cycles.
    """

    def __init__(self) -> None:
        self.size = config.temperature_average_samples * 2
        self.status = [True for i in range(self.size)]
        self.limit = 30

    def good(self) -> None:
        """True is good!"""
        self.status.append(True)
        del self.status[0]

    def bad(self) -> None:
        """False is bad!"""
        self.status.append(False)
        del self.status[0]

    def error_percent(self) -> float:
        errors = sum(i == False for i in self.status)
        return (errors / self.size) * 100

    def over_error_limit(self) -> bool:
        if self.error_percent() > self.limit:
            return True
        return False


class Max31855(TempSensorReal):
    """each subclass expected to handle errors and get temperature"""

    def __init__(self) -> None:
        TempSensorReal.__init__(self)
        log.info("thermocouple MAX31855")
        import adafruit_max31855

        self.thermocouple = adafruit_max31855.MAX31855(self.spi, self.cs)

    def raw_temp(self) -> float:
        try:
            return self.thermocouple.temperature_NIST
        except RuntimeError as rte:
            if rte.args and rte.args[0]:
                raise Max31855_Error(rte.args[0])
            raise Max31855_Error("unknown")


class ThermocoupleError(Exception):
    """
    thermocouple exception parent class to handle mapping of error messages
    and make them consistent across adafruit libraries. Also set whether
    each exception should be ignored based on settings in config.py.
    """

    def __init__(self, message: str) -> None:
        self.ignore = False
        self.message = message
        self.map_message()
        self.set_ignore()
        super().__init__(self.message)

    def set_ignore(self) -> None:
        if self.message == "not connected" and config.ignore_tc_lost_connection == True:
            self.ignore = True
        if self.message == "short circuit" and config.ignore_tc_short_errors == True:
            self.ignore = True
        if self.message == "unknown" and config.ignore_tc_unknown_error == True:
            self.ignore = True
        if (
            self.message == "cold junction range fault"
            and config.ignore_tc_cold_junction_range_error == True
        ):
            self.ignore = True
        if self.message == "thermocouple range fault" and config.ignore_tc_range_error == True:
            self.ignore = True
        if (
            self.message == "cold junction temp too high"
            and config.ignore_tc_cold_junction_temp_high == True
        ):
            self.ignore = True
        if (
            self.message == "cold junction temp too low"
            and config.ignore_tc_cold_junction_temp_low == True
        ):
            self.ignore = True
        if self.message == "thermocouple temp too high" and config.ignore_tc_temp_high == True:
            self.ignore = True
        if self.message == "thermocouple temp too low" and config.ignore_tc_temp_low == True:
            self.ignore = True
        if self.message == "voltage too high or low" and config.ignore_tc_voltage_error == True:
            self.ignore = True

    def map_message(self) -> None:
        try:
            self.message = self.map[self.orig_message]
        except KeyError:
            self.message = "unknown"


class Max31855_Error(ThermocoupleError):
    """
    All children must set self.orig_message and self.map
    """

    def __init__(self, message: str) -> None:
        self.orig_message = message
        # this purposefully makes "fault reading" and
        # "Total thermoelectric voltage out of range..." unknown errors
        self.map = {
            "thermocouple not connected": "not connected",
            "short circuit to ground": "short circuit",
            "short circuit to power": "short circuit",
        }
        super().__init__(message)


class Max31856_Error(ThermocoupleError):
    def __init__(self, message: str) -> None:
        self.orig_message = message
        self.map = {
            "cj_range": "cold junction range fault",
            "tc_range": "thermocouple range fault",
            "cj_high": "cold junction temp too high",
            "cj_low": "cold junction temp too low",
            "tc_high": "thermocouple temp too high",
            "tc_low": "thermocouple temp too low",
            "voltage": "voltage too high or low",
            "open_tc": "not connected",
            "communication_failure": "SPI communication failure (all zeros received)",
        }
        super().__init__(message)


class Max31856(TempSensorReal):
    """each subclass expected to handle errors and get temperature"""

    def __init__(self) -> None:
        TempSensorReal.__init__(self)
        log.info("thermocouple MAX31856")
        import adafruit_max31856

        self.thermocouple = adafruit_max31856.MAX31856(
            self.spi, self.cs, thermocouple_type=config.thermocouple_type
        )
        if config.ac_freq_50hz == True:
            self.thermocouple.noise_rejection = 50
        else:
            self.thermocouple.noise_rejection = 60

    def raw_temp(self) -> float:
        # The underlying adafruit library does not throw exceptions
        # for thermocouple errors. Instead, they are stored in
        # dict named self.thermocouple.fault. Here we check that
        # dict for errors and raise an exception.
        # and raise Max31856_Error(message)
        temp = self.thermocouple.temperature

        # Check for communication failure (all zeros received over SPI)
        # This manifests as both board temp and probe temp being exactly 0.0C (32.00F)
        # with no faults flagged by the chip hardware.
        ref_temp = self.thermocouple.reference_temperature
        if temp == 0.0 and ref_temp == 0.0:
            if not any(self.thermocouple.fault.values()):
                raise Max31856_Error("communication_failure")

        for k, v in self.thermocouple.fault.items():
            if v:
                raise Max31856_Error(k)
        return temp


class Oven(threading.Thread):
    """parent oven class. this has all the common code
    for either a real or simulated oven"""

    def __init__(self, buzzer: Any | None = None) -> None:
        threading.Thread.__init__(self)
        self.daemon = True
        self.temperature = 0
        self.time_step = config.sensor_time_wait
        self.buzzer = buzzer
        self.notifier = None
        self.firing_record = FiringRecordWriter(
            enabled=bool(getattr(config, "firing_record_enabled", True)),
            output_dir=getattr(config, "firing_record_directory", None),
            flush_each_row=bool(getattr(config, "firing_record_flush_each_row", True)),
        )
        self.current_firing_log_file = None
        self.reset()

    def reset(self) -> None:
        self.cost = 0
        self.state = "IDLE"
        self.profile = None
        self.start_time = 0
        self.runtime = 0
        self.totaltime = 0
        self.target = 0
        self.heat = 0
        self.heat_rate = 0
        self.heat_rate_temps = []
        self.pid = PID(ki=config.pid_ki, kd=config.pid_kd, kp=config.pid_kp)
        self.catching_up = False
        self._init_telemetry()

    def _init_telemetry(self) -> None:
        confidence_window = float(
            getattr(config, "catchup_supervisor_confidence_window_seconds", 1800.0)
        )
        self.telemetry_window_seconds = int(max(300.0, confidence_window))
        self.telemetry_samples = deque()
        self.telemetry_switches_5m = deque()
        self.telemetry_last_heat_state = None
        self.telemetry_last_sample_runtime = None
        self.telemetry_last_runtime = 0
        self.telemetry_last_catching_up = False
        self.telemetry_run_samples = 0
        self.telemetry_run_within_5deg = 0
        self.telemetry_run_error_sum = 0.0
        self.telemetry_run_error_abs_sum = 0.0
        self.telemetry_run_switches = 0
        self.telemetry_run_overshoot_max = 0.0
        self.telemetry_run_catching_up_seconds = 0.0
        self.telemetry_run_heat_on_seconds = 0.0
        self.telemetry_run_high_temp_seconds = 0.0
        self.telemetry_run_high_temp_heat_on_seconds = 0.0
        self.telemetry_run_high_temp_error_abs_sum = 0.0
        self.telemetry_run_high_temp_samples = 0
        self.telemetry_run_max_temp = 0.0
        self.telemetry_run_max_target = 0.0
        self.telemetry_run_line_power_sum = 0.0
        self.telemetry_run_line_current_sum = 0.0
        self.telemetry_run_line_voltage_sum = 0.0
        self.telemetry_run_line_samples = 0
        self.telemetry_run_line_energy_wh_last = 0.0
        self.telemetry_run_no_current_heating_seconds = 0.0
        self.telemetry_no_current_streak_seconds = 0.0
        self.telemetry_run_power_sensor_stale_seconds = 0.0
        self.telemetry_power_sensor_stale_streak_seconds = 0.0
        self.current_run_id = None
        self.current_run_started_ts = None
        self.current_run_peak_target = None
        self.alert_last_sent_at = {}
        self.alert_sent_once = set()
        self.next_profile_checkpoint_index = None
        self.next_temp_milestone = None
        self.telemetry_last_power_log_ts = 0.0
        self.catchup_shadow_state = "normal"
        self.catchup_shadow_last_change_runtime = 0.0
        self.catchup_shadow_avg_error_confidence = 0.0
        self.catchup_shadow_rise_rate_trend = 0.0
        self.catchup_shadow_duty_cycle_confidence_pct = 0.0
        self.catchup_shadow_lagging_seconds = 0.0
        self.catchup_shadow_cusum_deg_seconds = 0.0
        self.catchup_shadow_holdoff_until_runtime = 0.0
        self.catchup_shadow_last_log_ts = 0.0
        self.catchup_shadow_holdoff_active = False
        if not hasattr(self, "last_run_summary"):
            self.last_run_summary = None

    def _get_power_snapshot(self) -> dict[str, Any]:
        sensor = getattr(self.board, "power_sensor", None)
        if not sensor:
            return NullPowerSensor(reason="missing").snapshot()
        try:
            return sensor.snapshot()
        except Exception as exc:
            log.debug("power sensor snapshot failed: %s", exc)
            return NullPowerSensor(reason="read error").snapshot()

    @staticmethod
    def _scale_power_value(value: Any) -> float | None:
        """Scale current, power, and energy readings using configured factor."""
        if value is None:
            return None
        scale = float(getattr(config, "power_sensor_scale_factor", 1.0))
        return float(value) * scale

    def _record_telemetry_sample(self, temp: float) -> None:
        """Capture one telemetry sample per control-cycle-sized runtime increment."""
        # Record telemetry only once per control-cycle-sized runtime progression.
        if self.state not in ("RUNNING", "PAUSED"):
            return
        if self.telemetry_last_sample_runtime is not None:
            if abs(self.runtime - self.telemetry_last_sample_runtime) < 0.5:
                return
        self.telemetry_last_sample_runtime = self.runtime

        now = time.time()
        error = self.target - temp
        abs_error = abs(error)
        within_5deg = abs_error <= 5
        heat_on = 1 if self.heat > 0 else 0
        overshoot = max(0.0, temp - self.target)
        power = self._get_power_snapshot()
        line_voltage = power.get("voltage")
        raw_line_current = power.get("current")
        raw_line_power = power.get("power")
        raw_line_energy_wh = power.get("energy_wh")
        line_current = self._scale_power_value(raw_line_current)
        line_power = self._scale_power_value(raw_line_power)
        line_energy_wh = self._scale_power_value(raw_line_energy_wh)
        power_sensor_stale = bool(power.get("stale", True))
        power_sensor_error_pct = float(power.get("error_rate_pct", 100.0))

        if self.telemetry_last_heat_state is not None and heat_on != self.telemetry_last_heat_state:
            self.telemetry_run_switches += 1
            self.telemetry_switches_5m.append(now)
        self.telemetry_last_heat_state = heat_on

        runtime_delta = max(0.0, self.runtime - self.telemetry_last_runtime)
        prev_runtime = self.telemetry_last_runtime
        if self.telemetry_last_runtime > 0 and self.telemetry_last_catching_up:
            self.telemetry_run_catching_up_seconds += runtime_delta
        if prev_runtime > 0 and heat_on:
            self.telemetry_run_heat_on_seconds += runtime_delta
        if prev_runtime > 0 and power_sensor_stale:
            self.telemetry_run_power_sensor_stale_seconds += runtime_delta
            self.telemetry_power_sensor_stale_streak_seconds += runtime_delta
        else:
            self.telemetry_power_sensor_stale_streak_seconds = 0.0
        self.telemetry_last_runtime = self.runtime
        self.telemetry_last_catching_up = self.catching_up

        self.telemetry_run_samples += 1
        self.telemetry_run_error_sum += error
        self.telemetry_run_error_abs_sum += abs_error
        if within_5deg:
            self.telemetry_run_within_5deg += 1
        if overshoot > self.telemetry_run_overshoot_max:
            self.telemetry_run_overshoot_max = overshoot
        if temp > self.telemetry_run_max_temp:
            self.telemetry_run_max_temp = temp
        if self.target > self.telemetry_run_max_target:
            self.telemetry_run_max_target = self.target
        if line_voltage is not None and line_current is not None and line_power is not None:
            self.telemetry_run_line_voltage_sum += float(line_voltage)
            self.telemetry_run_line_current_sum += float(line_current)
            self.telemetry_run_line_power_sum += float(line_power)
            self.telemetry_run_line_samples += 1
        if line_energy_wh is not None:
            self.telemetry_run_line_energy_wh_last = float(line_energy_wh)

        if self.current_run_peak_target and self.current_run_peak_target > 0:
            high_temp_threshold = self.current_run_peak_target * 0.9
            if self.target >= high_temp_threshold:
                self.telemetry_run_high_temp_seconds += runtime_delta
                if heat_on:
                    self.telemetry_run_high_temp_heat_on_seconds += runtime_delta
                self.telemetry_run_high_temp_error_abs_sum += abs_error
                self.telemetry_run_high_temp_samples += 1

        mismatch_min_error = float(getattr(config, "power_sensor_mismatch_min_error", 15.0))
        current_threshold = float(getattr(config, "power_sensor_current_threshold_amps", 0.25))
        mismatch_window = float(getattr(config, "power_sensor_no_current_window_seconds", 30.0))
        mismatch_cooldown = float(getattr(config, "power_sensor_mismatch_cooldown_seconds", 300.0))
        stale_alert_seconds = float(getattr(config, "power_sensor_stale_alert_seconds", 30.0))
        if prev_runtime > 0 and heat_on and (self.target - temp) >= mismatch_min_error:
            if line_current is not None and float(line_current) <= current_threshold:
                self.telemetry_run_no_current_heating_seconds += runtime_delta
                self.telemetry_no_current_streak_seconds += runtime_delta
            else:
                self.telemetry_no_current_streak_seconds = 0.0
        else:
            self.telemetry_no_current_streak_seconds = 0.0

        if self.telemetry_no_current_streak_seconds >= mismatch_window:
            self._notify_with_cooldown(
                key="heater_no_current",
                event="issue_detected",
                payload={
                    "profile": self.profile.name if self.profile else None,
                    "run_id": self.current_run_id,
                    "issue": "heater_commanded_no_current",
                    "current_amps": float(line_current) if line_current is not None else None,
                    "threshold_amps": current_threshold,
                    "window_seconds": mismatch_window,
                    "runtime_hours": self.runtime / 3600.0 if self.runtime else 0.0,
                },
                cooldown_seconds=mismatch_cooldown,
            )

        if (
            power.get("available", False)
            and self.telemetry_power_sensor_stale_streak_seconds >= stale_alert_seconds
        ):
            self._notify_with_cooldown(
                key="power_sensor_stale",
                event="issue_detected",
                payload={
                    "profile": self.profile.name if self.profile else None,
                    "run_id": self.current_run_id,
                    "issue": "power_sensor_stale",
                    "stale_seconds": self.telemetry_power_sensor_stale_streak_seconds,
                },
                cooldown_seconds=float(
                    getattr(config, "power_sensor_stale_cooldown_seconds", 300.0)
                ),
            )

        sample = {
            "time": now,
            "runtime": self.runtime,
            "error": error,
            "abs_error": abs_error,
            "heat_on": heat_on,
            "within_5deg": within_5deg,
            "temperature": temp,
            "target": self.target,
            "catching_up": self.catching_up,
            "sensor_error_percent": self.board.temp_sensor.status.error_percent(),
            "line_voltage": line_voltage,
            "line_current": line_current,
            "line_power": line_power,
            "line_energy_wh": line_energy_wh,
            "line_current_raw": raw_line_current,
            "line_power_raw": raw_line_power,
            "line_energy_wh_raw": raw_line_energy_wh,
            "power_sensor_stale": power_sensor_stale,
            "power_sensor_error_percent": power_sensor_error_pct,
            "power_factor": power.get("power_factor"),
        }
        self.telemetry_samples.append(sample)
        self._persist_power_telemetry_sample(now=now, sample=sample)

        cutoff = now - self.telemetry_window_seconds
        while self.telemetry_samples and self.telemetry_samples[0]["time"] < cutoff:
            self.telemetry_samples.popleft()
        while self.telemetry_switches_5m and self.telemetry_switches_5m[0] < cutoff:
            self.telemetry_switches_5m.popleft()
        self._check_catchup_supervisor_shadow(
            now=now,
            error=error,
            runtime_delta=runtime_delta,
        )
        self._check_runtime_alerts(now, temp, error)

    def _persist_power_telemetry_sample(self, now: float, sample: dict[str, Any]) -> None:
        """Append one power-telemetry JSONL row when logging is enabled."""
        if not bool(getattr(config, "power_telemetry_log_enabled", False)):
            return
        interval = float(getattr(config, "power_telemetry_log_interval_seconds", 2.0))
        if interval > 0 and self.telemetry_last_power_log_ts > 0:
            if (now - self.telemetry_last_power_log_ts) < interval:
                return
        self.telemetry_last_power_log_ts = now

        row = {
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "unix_time": now,
            "run_id": self.current_run_id,
            "profile": self.profile.name if self.profile else None,
            "state": self.state,
            "runtime_seconds": self.runtime,
            "heat_command": self.heat,
            "heat_on": sample.get("heat_on"),
            "temperature": sample.get("temperature"),
            "target": sample.get("target"),
            "error": sample.get("error"),
            "line_voltage": sample.get("line_voltage"),
            "line_current": sample.get("line_current"),
            "line_power": sample.get("line_power"),
            "line_energy_wh": sample.get("line_energy_wh"),
            "line_current_raw": sample.get("line_current_raw"),
            "line_power_raw": sample.get("line_power_raw"),
            "line_energy_wh_raw": sample.get("line_energy_wh_raw"),
            "power_scale_factor": float(getattr(config, "power_sensor_scale_factor", 1.0)),
            "power_factor": sample.get("power_factor"),
            "power_sensor_stale": sample.get("power_sensor_stale"),
            "power_sensor_error_percent": sample.get("power_sensor_error_percent"),
            "sensor_error_percent": sample.get("sensor_error_percent"),
        }
        try:
            os.makedirs(os.path.dirname(config.power_telemetry_log_file), exist_ok=True)
            with open(config.power_telemetry_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except Exception as exc:
            log.error("failed writing power telemetry log: %s", exc)

    @staticmethod
    def _samples_since(
        samples: list[dict[str, Any]], now: float, window_seconds: float
    ) -> list[dict[str, Any]]:
        cutoff = now - max(1.0, float(window_seconds))
        return [sample for sample in samples if sample["time"] >= cutoff]

    @staticmethod
    def _rise_rate_deg_per_hour(samples: list[dict[str, Any]]) -> float:
        if len(samples) < 2:
            return 0.0
        t0 = float(samples[0]["time"])
        t1 = float(samples[-1]["time"])
        if t1 <= t0:
            return 0.0
        temp0 = float(samples[0]["temperature"])
        temp1 = float(samples[-1]["temperature"])
        return ((temp1 - temp0) / (t1 - t0)) * 3600.0

    def _persist_catchup_shadow_decision(
        self, now: float, decision: str, reason: str, force: bool = False
    ) -> None:
        if not bool(getattr(config, "catchup_shadow_log_enabled", False)):
            return
        interval = float(getattr(config, "catchup_shadow_log_interval_seconds", 30.0))
        if not force and interval > 0 and self.catchup_shadow_last_log_ts > 0:
            if (now - self.catchup_shadow_last_log_ts) < interval:
                return
        self.catchup_shadow_last_log_ts = now

        row = {
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "unix_time": now,
            "run_id": self.current_run_id,
            "profile": self.profile.name if self.profile else None,
            "mode": str(getattr(config, "catchup_supervisor_mode", "shadow")),
            "decision": decision,
            "reason": reason,
            "runtime_seconds": self.runtime,
            "temperature": self.temperature,
            "target": self.target,
            "error": self.target - self.temperature,
            "avg_error_confidence": self.catchup_shadow_avg_error_confidence,
            "rise_rate_trend_deg_per_hour": self.catchup_shadow_rise_rate_trend,
            "duty_cycle_confidence_pct": self.catchup_shadow_duty_cycle_confidence_pct,
            "lagging_seconds": self.catchup_shadow_lagging_seconds,
            "cusum_deg_seconds": self.catchup_shadow_cusum_deg_seconds,
            "holdoff_active": self.catchup_shadow_holdoff_active,
            "holdoff_until_runtime": self.catchup_shadow_holdoff_until_runtime,
        }
        try:
            os.makedirs(os.path.dirname(config.catchup_shadow_log_file), exist_ok=True)
            with open(config.catchup_shadow_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except Exception as exc:
            log.error("failed writing catchup shadow log: %s", exc)

    def _check_catchup_supervisor_shadow(
        self,
        now: float,
        error: float,
        runtime_delta: float,
    ) -> None:
        if not bool(getattr(config, "catchup_supervisor_enabled", True)):
            return
        if self.state != "RUNNING" or not self.profile:
            return

        min_runtime = float(getattr(config, "catchup_supervisor_min_runtime_seconds", 1800.0))
        min_target = float(getattr(config, "catchup_supervisor_min_target_temp", 900.0))
        if self.runtime < min_runtime or self.target < min_target:
            self.catchup_shadow_state = "normal"
            self.catchup_shadow_holdoff_active = False
            return

        fast_window = float(getattr(config, "catchup_supervisor_fast_window_seconds", 180.0))
        trend_window = float(getattr(config, "catchup_supervisor_trend_window_seconds", 900.0))
        confidence_window = float(
            getattr(config, "catchup_supervisor_confidence_window_seconds", 1800.0)
        )
        recent = list(self.telemetry_samples)
        fast_samples = self._samples_since(recent, now, fast_window)
        trend_samples = self._samples_since(recent, now, trend_window)
        confidence_samples = self._samples_since(recent, now, confidence_window)

        if len(confidence_samples) < 2:
            return

        avg_error_confidence = avg([float(sample["error"]) for sample in confidence_samples])
        duty_cycle_confidence_pct = (
            avg([float(sample["heat_on"]) for sample in confidence_samples]) * 100.0
        )
        rise_rate_fast = self._rise_rate_deg_per_hour(fast_samples)
        rise_rate_trend = self._rise_rate_deg_per_hour(trend_samples)

        transient_drop_window = float(
            getattr(config, "catchup_supervisor_transient_drop_window_seconds", 90.0)
        )
        transient_drop_threshold = float(
            getattr(config, "catchup_supervisor_transient_drop_threshold", 20.0)
        )
        transient_holdoff = float(
            getattr(config, "catchup_supervisor_transient_holdoff_seconds", 900.0)
        )
        transient_samples = self._samples_since(recent, now, transient_drop_window)
        if len(transient_samples) >= 2:
            drop = float(transient_samples[-1]["temperature"]) - float(
                transient_samples[0]["temperature"]
            )
            if drop <= -abs(transient_drop_threshold) and error > float(config.pid_control_window):
                self.catchup_shadow_holdoff_until_runtime = max(
                    self.catchup_shadow_holdoff_until_runtime,
                    self.runtime + transient_holdoff,
                )

        self.catchup_shadow_holdoff_active = (
            self.runtime < self.catchup_shadow_holdoff_until_runtime
        )

        lag_threshold = float(getattr(config, "catchup_supervisor_error_threshold", 50.0))
        if avg_error_confidence >= lag_threshold:
            self.catchup_shadow_lagging_seconds += max(0.0, runtime_delta)
        else:
            self.catchup_shadow_lagging_seconds = max(
                0.0, self.catchup_shadow_lagging_seconds - max(0.0, runtime_delta) * 2.0
            )

        cusum_decay_rate = float(
            getattr(config, "catchup_supervisor_cusum_decay_deg_seconds_per_second", 5.0)
        )
        residual = max(0.0, avg_error_confidence - lag_threshold)
        self.catchup_shadow_cusum_deg_seconds += residual * max(0.0, runtime_delta)
        if residual <= 0:
            self.catchup_shadow_cusum_deg_seconds = max(
                0.0,
                self.catchup_shadow_cusum_deg_seconds
                - (cusum_decay_rate * max(0.0, runtime_delta)),
            )

        decision = decide_catchup_shadow_state(
            avg_error_confidence=avg_error_confidence,
            rise_rate_trend=rise_rate_trend,
            duty_cycle_confidence_pct=duty_cycle_confidence_pct,
            lagging_seconds=self.catchup_shadow_lagging_seconds,
            cusum_deg_seconds=self.catchup_shadow_cusum_deg_seconds,
            holdoff_active=self.catchup_shadow_holdoff_active,
        )
        previous_state = self.catchup_shadow_state
        self.catchup_shadow_state = decision
        self.catchup_shadow_avg_error_confidence = avg_error_confidence
        self.catchup_shadow_rise_rate_trend = rise_rate_trend
        self.catchup_shadow_duty_cycle_confidence_pct = duty_cycle_confidence_pct

        if previous_state != decision:
            self.catchup_shadow_last_change_runtime = self.runtime
            log.warning(
                "catchup supervisor (%s): %s -> %s (avg_error=%.1f, rise_trend=%.1f/h, rise_fast=%.1f/h, duty=%.1f%%, lagging_s=%.0f, cusum=%.0f, holdoff=%s)",
                str(getattr(config, "catchup_supervisor_mode", "shadow")),
                previous_state,
                decision,
                avg_error_confidence,
                rise_rate_trend,
                rise_rate_fast,
                duty_cycle_confidence_pct,
                self.catchup_shadow_lagging_seconds,
                self.catchup_shadow_cusum_deg_seconds,
                self.catchup_shadow_holdoff_active,
            )
            self._persist_catchup_shadow_decision(
                now=now, decision=decision, reason="state_change", force=True
            )
            payload = {
                "profile": self.profile.name if self.profile else None,
                "run_id": self.current_run_id,
                "mode": str(getattr(config, "catchup_supervisor_mode", "shadow")),
                "decision": decision,
                "avg_error_confidence": avg_error_confidence,
                "rise_rate_trend_deg_per_hour": rise_rate_trend,
                "duty_cycle_confidence_pct": duty_cycle_confidence_pct,
                "lagging_seconds": self.catchup_shadow_lagging_seconds,
                "cusum_deg_seconds": self.catchup_shadow_cusum_deg_seconds,
                "runtime_hours": self.runtime / 3600.0 if self.runtime else 0.0,
            }
            if decision == "would_abort":
                self._notify_with_cooldown(
                    key="catchup_shadow_would_abort",
                    event="issue_detected",
                    payload={**payload, "issue": "catchup_shadow_would_abort"},
                    cooldown_seconds=600.0,
                )
            elif decision == "would_extend":
                self._notify_with_cooldown(
                    key="catchup_shadow_would_extend",
                    event="issue_detected",
                    payload={**payload, "issue": "catchup_shadow_would_extend"},
                    cooldown_seconds=1800.0,
                )
        else:
            self._persist_catchup_shadow_decision(
                now=now, decision=decision, reason="interval", force=False
            )

    def _notify_with_cooldown(
        self,
        key: str,
        event: str,
        payload: dict[str, Any],
        cooldown_seconds: float | None = None,
    ) -> bool:
        if cooldown_seconds is None:
            cooldown_seconds = float(getattr(config, "notifications_alert_cooldown_seconds", 300))
        now = time.time()
        last_ts = self.alert_last_sent_at.get(key)
        if last_ts is not None and (now - last_ts) < cooldown_seconds:
            return False
        self.alert_last_sent_at[key] = now
        self._notify_event(event, payload)
        return True

    def _notify_once_per_run(self, key: str, event: str, payload: dict[str, Any]) -> bool:
        if key in self.alert_sent_once:
            return False
        self.alert_sent_once.add(key)
        self._notify_event(event, payload)
        return True

    def _check_runtime_alerts(self, now: float, temp: float, error: float) -> None:
        if self.state != "RUNNING" or not self.profile:
            return
        self._check_profile_rate_change_alert()
        self._check_temp_milestone_alert(temp)
        self._check_abnormal_deviation_alert(now, temp, error)

    def _check_profile_rate_change_alert(self) -> None:
        points = self.profile.data if self.profile else []
        if len(points) < 3:
            return
        if self.next_profile_checkpoint_index is None:
            for idx in range(1, len(points) - 1):
                if points[idx][0] > self.runtime:
                    self.next_profile_checkpoint_index = idx
                    break
            if self.next_profile_checkpoint_index is None:
                self.next_profile_checkpoint_index = len(points) - 1

        while (
            self.next_profile_checkpoint_index is not None
            and self.next_profile_checkpoint_index < len(points) - 1
        ):
            idx = self.next_profile_checkpoint_index
            checkpoint_time = points[idx][0]
            if self.runtime < checkpoint_time:
                break

            prev_point = points[idx - 1]
            curr_point = points[idx]
            next_point = points[idx + 1]
            prev_slope = 0.0
            next_slope = 0.0
            if curr_point[0] > prev_point[0]:
                prev_slope = (
                    (curr_point[1] - prev_point[1]) / float(curr_point[0] - prev_point[0]) * 3600.0
                )
            if next_point[0] > curr_point[0]:
                next_slope = (
                    (next_point[1] - curr_point[1]) / float(next_point[0] - curr_point[0]) * 3600.0
                )

            self._notify_once_per_run(
                key="rate_change_%d" % idx,
                event="profile_rate_change",
                payload={
                    "profile": self.profile.name if self.profile else None,
                    "run_id": self.current_run_id,
                    "checkpoint_seconds": checkpoint_time,
                    "checkpoint_hours": checkpoint_time / 3600.0,
                    "temperature_target": curr_point[1],
                    "previous_rate_deg_per_hour": prev_slope,
                    "new_rate_deg_per_hour": next_slope,
                },
            )
            self.next_profile_checkpoint_index = idx + 1

    def _check_temp_milestone_alert(self, temp: float) -> None:
        interval = float(getattr(config, "notifications_temp_milestone_interval", 500))
        if interval <= 0:
            return
        if self.next_temp_milestone is None:
            self.next_temp_milestone = math.floor(max(0.0, temp) / interval) * interval + interval

        while self.next_temp_milestone is not None and temp >= self.next_temp_milestone:
            milestone = self.next_temp_milestone
            self._notify_once_per_run(
                key="temp_milestone_%d" % int(milestone),
                event="temp_milestone_reached",
                payload={
                    "profile": self.profile.name if self.profile else None,
                    "run_id": self.current_run_id,
                    "milestone_temp": milestone,
                    "temperature": temp,
                    "target": self.target,
                    "runtime_hours": self.runtime / 3600.0 if self.runtime else 0.0,
                },
            )
            self.next_temp_milestone += interval

    def _check_abnormal_deviation_alert(self, now: float, temp: float, error: float) -> None:
        drop_window = float(getattr(config, "notifications_deviation_drop_window_seconds", 45))
        drop_threshold = float(getattr(config, "notifications_deviation_drop_threshold", 20))
        min_error = float(getattr(config, "notifications_deviation_min_error", 35))
        min_target = float(getattr(config, "notifications_deviation_min_target_temp", 300))

        if self.target < min_target or error < min_error or self.heat <= 0:
            return

        sample = None
        cutoff = now - drop_window
        for item in self.telemetry_samples:
            if item["time"] >= cutoff:
                sample = item
                break
        if not sample:
            return

        temp_drop = temp - sample["temperature"]
        if temp_drop <= -abs(drop_threshold):
            self._notify_with_cooldown(
                key="abnormal_deviation",
                event="abnormal_deviation",
                payload={
                    "profile": self.profile.name if self.profile else None,
                    "run_id": self.current_run_id,
                    "temperature": temp,
                    "target": self.target,
                    "error": error,
                    "drop_window_seconds": drop_window,
                    "temperature_drop": temp_drop,
                    "runtime_hours": self.runtime / 3600.0 if self.runtime else 0.0,
                },
                cooldown_seconds=float(
                    getattr(config, "notifications_deviation_cooldown_seconds", 300)
                ),
            )

    def get_telemetry(self) -> dict[str, Any]:
        recent = list(self.telemetry_samples)
        errors = [sample["error"] for sample in recent]
        abs_errors = [sample["abs_error"] for sample in recent]
        heat = [sample["heat_on"] for sample in recent]
        within = [sample["within_5deg"] for sample in recent]
        sensor_errors = [sample["sensor_error_percent"] for sample in recent]
        line_voltages = [
            sample["line_voltage"] for sample in recent if sample["line_voltage"] is not None
        ]
        line_currents = [
            sample["line_current"] for sample in recent if sample["line_current"] is not None
        ]
        line_powers = [
            sample["line_power"] for sample in recent if sample["line_power"] is not None
        ]
        power_sensor_stale = [sample["power_sensor_stale"] for sample in recent]
        power_sensor_errors = [sample["power_sensor_error_percent"] for sample in recent]
        latest_line_energy = next(
            (
                sample["line_energy_wh"]
                for sample in reversed(recent)
                if sample["line_energy_wh"] is not None
            ),
            self.telemetry_run_line_energy_wh_last,
        )

        one_minute_cutoff = time.time() - 60
        recent_1m_errors = [
            sample["error"] for sample in recent if sample["time"] >= one_minute_cutoff
        ]

        runtime_hours = self.runtime / 3600 if self.runtime > 0 else 0
        switches_per_hour = (
            self.telemetry_run_switches / runtime_hours if runtime_hours > 0 else 0.0
        )
        within_5deg_run = (
            (self.telemetry_run_within_5deg / float(self.telemetry_run_samples)) * 100
            if self.telemetry_run_samples
            else 0.0
        )
        catching_up_pct_run = (
            (self.telemetry_run_catching_up_seconds / self.runtime) * 100
            if self.runtime > 0
            else 0.0
        )
        no_current_pct_run = (
            (self.telemetry_run_no_current_heating_seconds / self.telemetry_run_heat_on_seconds)
            * 100
            if self.telemetry_run_heat_on_seconds > 0
            else 0.0
        )
        power = self._get_power_snapshot()
        line_current_now = self._scale_power_value(power.get("current"))
        line_power_now = self._scale_power_value(power.get("power"))
        line_energy_wh_now = self._scale_power_value(power.get("energy_wh"))

        return {
            "window_seconds": self.telemetry_window_seconds,
            "error_now": self.target - self.temperature,
            "error_avg_1m": avg(recent_1m_errors),
            "error_avg_5m": avg(errors),
            "error_abs_avg_5m": avg(abs_errors),
            "within_5deg_pct_5m": bool_pct(within),
            "within_5deg_pct_run": within_5deg_run,
            "switches_5m": len(self.telemetry_switches_5m),
            "switches_per_hour_run": switches_per_hour,
            "duty_cycle_5m": avg(heat) * 100,
            "overshoot_max_run": self.telemetry_run_overshoot_max,
            "time_catching_up_pct_run": catching_up_pct_run,
            "sensor_error_rate_5m": avg(sensor_errors),
            "power_sensor_available": bool(power.get("available", False)),
            "power_sensor_ok": bool(power.get("ok", False)),
            "power_sensor_stale_5m": bool_pct(power_sensor_stale),
            "power_sensor_error_rate_5m": avg(power_sensor_errors),
            "line_voltage_now": power.get("voltage"),
            "line_current_now": line_current_now,
            "line_power_now": line_power_now,
            "line_energy_wh_now": line_energy_wh_now,
            "line_voltage_avg_5m": avg(line_voltages),
            "line_current_avg_5m": avg(line_currents),
            "line_power_avg_5m": avg(line_powers),
            "line_energy_wh_last_5m": latest_line_energy,
            "no_current_when_heating_pct_run": no_current_pct_run,
            "catchup_supervisor_enabled": bool(getattr(config, "catchup_supervisor_enabled", True)),
            "catchup_supervisor_mode": str(getattr(config, "catchup_supervisor_mode", "shadow")),
            "catchup_shadow_state": self.catchup_shadow_state,
            "catchup_shadow_avg_error_confidence": self.catchup_shadow_avg_error_confidence,
            "catchup_shadow_rise_rate_trend_deg_per_hour": self.catchup_shadow_rise_rate_trend,
            "catchup_shadow_duty_cycle_confidence_pct": self.catchup_shadow_duty_cycle_confidence_pct,
            "catchup_shadow_lagging_seconds": self.catchup_shadow_lagging_seconds,
            "catchup_shadow_cusum_deg_seconds": self.catchup_shadow_cusum_deg_seconds,
            "catchup_shadow_holdoff_active": self.catchup_shadow_holdoff_active,
        }

    @staticmethod
    def get_start_from_temperature(profile: Profile, temp: float) -> float:
        target_temp = profile.get_target_temperature(0)
        if temp > target_temp + 5:
            startat = profile.find_next_time_from_temperature(temp)
            log.info(f"seek_start is in effect, starting at: {round(startat)} s, {round(temp)} deg")
        else:
            startat = 0
        return startat

    def set_heat_rate(self, runtime: float, temp: float) -> None:
        """Estimate heating rate in degrees per hour from recent samples."""
        # Keep a fixed-size rolling sample window; the covered time span varies.
        numtemps = 60
        self.heat_rate_temps.append((runtime, temp))

        # Drop the oldest samples when the rolling window grows too large.
        if len(self.heat_rate_temps) > numtemps:
            self.heat_rate_temps = self.heat_rate_temps[-1 * numtemps :]
        time2 = self.heat_rate_temps[-1][0]
        time1 = self.heat_rate_temps[0][0]
        temp2 = self.heat_rate_temps[-1][1]
        temp1 = self.heat_rate_temps[0][1]
        if time2 > time1:
            self.heat_rate = ((temp2 - temp1) / (time2 - time1)) * 3600

    def run_profile(self, profile: Profile, startat: float = 0, allow_seek: bool = True) -> None:
        """Start executing a profile, optionally resuming at a minute offset."""
        log.debug("run_profile run on thread" + threading.current_thread().name)

        # Play the start sound without blocking the control path.
        if self.buzzer:
            threading.Thread(target=self.buzzer.start_firing).start()

        runtime = startat * 60
        if allow_seek:
            if self.state == "IDLE":
                if config.seek_start:
                    # Temperature access is implemented by the concrete board sensor.
                    temp = self.board.temp_sensor.temperature()
                    runtime += self.get_start_from_temperature(profile, temp)

        self.firing_record.close()
        self.current_firing_log_file = None
        self.reset()
        self.startat = startat * 60
        self.runtime = runtime
        self.start_time = datetime.datetime.now() - datetime.timedelta(seconds=self.startat)
        self.profile = profile
        self.totaltime = profile.get_duration()
        self.current_run_id = str(uuid.uuid4())
        self.current_run_started_ts = time.time()
        self.current_run_peak_target = max((temp for (_, temp) in profile.data), default=0)
        self.next_profile_checkpoint_index = None
        self.next_temp_milestone = None
        self.current_run_summary = None
        self.last_run_summary = None
        self.state = "RUNNING"
        log.info("Running schedule %s starting at %d minutes" % (profile.name, startat))
        log.info("Starting")
        self._notify_event(
            "run_started",
            {
                "profile": profile.name,
                "startat_minutes": startat,
                "run_id": self.current_run_id,
            },
        )
        self._start_firing_record(profile=profile, startat_seconds=self.startat)

    def _start_firing_record(self, profile: Profile, startat_seconds: float) -> None:
        """Open the append-only firing record for the active run."""
        metadata = {
            "profile_data": profile.data,
            "temp_scale": getattr(config, "temp_scale", "f"),
            "sensor_time_wait": self.time_step,
            "thermocouple_offset": getattr(config, "thermocouple_offset", 0),
            "pid_kp": getattr(config, "pid_kp", None),
            "pid_ki": getattr(config, "pid_ki", None),
            "pid_kd": getattr(config, "pid_kd", None),
            "pid_control_window": getattr(config, "pid_control_window", None),
            "kiln_must_catch_up": getattr(config, "kiln_must_catch_up", None),
            "throttle_below_temp": getattr(config, "throttle_below_temp", None),
            "throttle_percent": getattr(config, "throttle_percent", None),
            "min_on_time": getattr(config, "min_on_time", None),
            "simulate": getattr(config, "simulate", None),
        }
        self.current_firing_log_file = self.firing_record.start_run(
            run_id=self.current_run_id or "unknown",
            profile_name=profile.name,
            startat_seconds=startat_seconds,
            total_seconds=self.totaltime,
            metadata=metadata,
        )

    def _sensor_error_percent(self) -> float:
        """Return the current thermocouple error percentage."""
        try:
            return float(self.board.temp_sensor.status.error_percent())
        except Exception:
            return 0.0

    def _record_firing_cycle(
        self,
        *,
        measured_temp: float,
        heat_on: float,
        heat_off: float,
        cycle_epoch: float | None = None,
        notes: str = "",
    ) -> None:
        if not self.current_run_id:
            return

        timestamp = cycle_epoch if cycle_epoch is not None else time.time()
        self.set_heat_rate(self.runtime, measured_temp)
        error = self.target - measured_temp
        runtime_hours = self.runtime / 3600 if self.runtime > 0 else 0.0
        switches_per_hour_run = (
            self.telemetry_run_switches / runtime_hours if runtime_hours > 0 else 0.0
        )
        pidstats = self.pid.pidstats if isinstance(self.pid.pidstats, dict) else {}

        self.firing_record.write_sample(
            {
                "row_type": "sample",
                "ts_utc": datetime.datetime.utcfromtimestamp(timestamp).isoformat() + "Z",
                "epoch_s": timestamp,
                "run_id": self.current_run_id,
                "profile": self.profile.name if self.profile else None,
                "state": self.state,
                "runtime_s": self.runtime,
                "total_s": self.totaltime,
                "time_left_s": max(0.0, self.totaltime - self.runtime),
                "startat_s": self.startat if hasattr(self, "startat") else 0.0,
                "temperature": measured_temp,
                "target": self.target,
                "error": error,
                "abs_error": abs(error),
                "within_5deg": abs(error) <= 5,
                "catching_up": self.catching_up,
                "relay_on": heat_on > 0,
                "heat_on_s": heat_on,
                "heat_off_s": heat_off,
                "pid_out": pidstats.get("out"),
                "pid_raw": pidstats.get("pid"),
                "pid_p": pidstats.get("p"),
                "pid_i": pidstats.get("i"),
                "pid_d": pidstats.get("d"),
                "pid_kp": pidstats.get("kp"),
                "pid_ki": pidstats.get("ki"),
                "pid_kd": pidstats.get("kd"),
                "heat_rate_deg_per_hour": self.heat_rate,
                "cost": self.cost,
                "sensor_error_pct": self._sensor_error_percent(),
                "switch_count_run": self.telemetry_run_switches,
                "switches_per_hour_run": switches_per_hour_run,
                "overshoot_max_run": self.telemetry_run_overshoot_max,
                "notes": notes,
            }
        )

    def get_run_health_summary(self, reason: str) -> dict[str, Any]:
        reason_info = describe_run_reason(
            reason,
            temperature=self.temperature,
            temp_limit=float(getattr(config, "emergency_shutoff_temp", 0)),
            sensor_error_pct=self._sensor_error_percent(),
            sensor_error_limit_pct=float(getattr(self.board.temp_sensor.status, "limit", 0)),
        )
        runtime_hours = self.runtime / 3600 if self.runtime > 0 else 0.0
        switches_per_hour = (
            self.telemetry_run_switches / runtime_hours if runtime_hours > 0 else 0.0
        )
        within_5deg_run = (
            (self.telemetry_run_within_5deg / float(self.telemetry_run_samples)) * 100
            if self.telemetry_run_samples
            else 0.0
        )
        heat_duty_run = (
            (self.telemetry_run_heat_on_seconds / self.runtime) * 100 if self.runtime > 0 else 0.0
        )
        high_temp_duty = (
            (self.telemetry_run_high_temp_heat_on_seconds / self.telemetry_run_high_temp_seconds)
            * 100
            if self.telemetry_run_high_temp_seconds > 0
            else 0.0
        )
        high_temp_mae = (
            self.telemetry_run_high_temp_error_abs_sum / float(self.telemetry_run_high_temp_samples)
            if self.telemetry_run_high_temp_samples
            else 0.0
        )
        peak_target = (
            self.current_run_peak_target
            if self.current_run_peak_target
            else self.telemetry_run_max_target
        )
        max_temp_gap_to_peak = peak_target - self.telemetry_run_max_temp if peak_target else 0.0
        no_current_pct = (
            (self.telemetry_run_no_current_heating_seconds / self.telemetry_run_heat_on_seconds)
            * 100
            if self.telemetry_run_heat_on_seconds > 0
            else 0.0
        )
        power_sensor_stale_pct = (
            (self.telemetry_run_power_sensor_stale_seconds / self.runtime) * 100
            if self.runtime > 0
            else 0.0
        )

        return {
            "run_id": self.current_run_id,
            "started_at": datetime.datetime.utcfromtimestamp(
                self.current_run_started_ts
            ).isoformat()
            + "Z"
            if self.current_run_started_ts
            else None,
            "ended_at": datetime.datetime.utcnow().isoformat() + "Z",
            "reason": reason,
            "reason_text": reason_info["reason_text"],
            "reason_kind": reason_info["reason_kind"],
            "profile": self.profile.name if self.profile else None,
            "runtime_seconds": self.runtime,
            "runtime_hours": runtime_hours,
            "cost": self.cost,
            "max_temp": self.telemetry_run_max_temp,
            "max_target": self.telemetry_run_max_target,
            "peak_profile_target": peak_target,
            "max_temp_gap_to_peak_target": max_temp_gap_to_peak,
            "overshoot_max": self.telemetry_run_overshoot_max,
            "within_5deg_pct": within_5deg_run,
            "switch_count": self.telemetry_run_switches,
            "switches_per_hour": switches_per_hour,
            "heat_duty_pct": heat_duty_run,
            "high_temp_seconds": self.telemetry_run_high_temp_seconds,
            "high_temp_duty_pct": high_temp_duty,
            "high_temp_mae": high_temp_mae,
            "catching_up_seconds": self.telemetry_run_catching_up_seconds,
            "catching_up_pct": (self.telemetry_run_catching_up_seconds / self.runtime) * 100
            if self.runtime > 0
            else 0.0,
            "sensor_error_rate_5m": avg(
                [sample["sensor_error_percent"] for sample in self.telemetry_samples]
            ),
            "line_voltage_avg_run": (
                self.telemetry_run_line_voltage_sum / float(self.telemetry_run_line_samples)
                if self.telemetry_run_line_samples
                else 0.0
            ),
            "line_current_avg_run": (
                self.telemetry_run_line_current_sum / float(self.telemetry_run_line_samples)
                if self.telemetry_run_line_samples
                else 0.0
            ),
            "line_power_avg_run": (
                self.telemetry_run_line_power_sum / float(self.telemetry_run_line_samples)
                if self.telemetry_run_line_samples
                else 0.0
            ),
            "line_energy_wh_last": self.telemetry_run_line_energy_wh_last,
            "no_current_when_heating_seconds": self.telemetry_run_no_current_heating_seconds,
            "no_current_when_heating_pct": no_current_pct,
            "power_sensor_stale_pct_run": power_sensor_stale_pct,
            "completed": reason == "schedule_complete",
        }

    def save_run_health_summary(self, summary: dict[str, Any]) -> None:
        if not getattr(config, "run_health_history_enabled", True):
            return
        try:
            os.makedirs(os.path.dirname(config.run_health_history_file), exist_ok=True)
            with open(config.run_health_history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(summary) + "\n")
        except Exception as error:
            log.error("failed writing run health history: %s", error)

    def finalize_run(self, reason: str = "abort") -> None:
        if self.state in ("RUNNING", "PAUSED") and self.profile:
            summary = self.get_run_health_summary(reason)
            if self.current_firing_log_file:
                summary["firing_record_file"] = self.current_firing_log_file
            self.last_run_summary = summary
            self.save_run_health_summary(summary)
            log.info(
                "run health summary saved for profile=%s reason=%s", summary.get("profile"), reason
            )
            self._notify_event("run_finished", summary)
            self.firing_record.end_run(reason=reason, summary=summary)
            self.firing_record.close()
            self.current_firing_log_file = None

    def abort_run(self, reason: str = "abort") -> None:
        if self.buzzer:
            if reason == "schedule_complete":
                self.buzzer.firing_complete()
            elif str(reason).startswith("manual_stop"):
                self.buzzer.manual_stop()
            elif str(reason).startswith("emergency"):
                self.buzzer.error()
        self.finalize_run(reason=reason)
        self.reset()
        self.save_automatic_restart_state()

    def get_start_time(self) -> datetime.datetime:
        """Return the virtual schedule start time for the current runtime."""
        return datetime.datetime.now() - datetime.timedelta(milliseconds=self.runtime * 1000)

    def kiln_must_catch_up(self) -> None:
        """Pause schedule time progression until kiln temperature re-enters the control window."""
        if config.kiln_must_catch_up == True:
            temp = self.board.temp_sensor.temperature() + config.thermocouple_offset
            # Shift schedule time when the kiln is still too cold.
            if self.target - temp > config.pid_control_window:
                log.info("kiln must catch up, too cold, shifting schedule")
                self.start_time = self.get_start_time()
                self.catching_up = True
                return
            # Shift schedule time when the kiln is still too hot.
            if temp - self.target > config.pid_control_window:
                log.info("kiln must catch up, too hot, shifting schedule")
                self.start_time = self.get_start_time()
                self.catching_up = True
                return
            self.catching_up = False

    def update_runtime(self) -> None:
        """Recompute runtime from the stored schedule start time."""
        runtime_delta = datetime.datetime.now() - self.start_time
        if runtime_delta.total_seconds() < 0:
            runtime_delta = datetime.timedelta(0)

        self.runtime = runtime_delta.total_seconds()

    def update_target_temp(self) -> None:
        """Update the active target temperature from the current profile runtime."""
        self.target = self.profile.get_target_temperature(self.runtime)

    def reset_if_emergency(self) -> None:
        """Abort the run when critical temperature or sensor faults are detected."""
        if (
            self.board.temp_sensor.temperature() + config.thermocouple_offset
            >= config.emergency_shutoff_temp
        ):
            log.info("emergency!!! temperature too high")
            self._notify_with_cooldown(
                key="temp_too_high",
                event="issue_detected",
                payload={
                    "profile": self.profile.name if self.profile else None,
                    "run_id": self.current_run_id,
                    "issue": "temperature_too_high",
                    "temperature": self.board.temp_sensor.temperature()
                    + config.thermocouple_offset,
                    "limit": config.emergency_shutoff_temp,
                },
                cooldown_seconds=60,
            )
            if config.ignore_temp_too_high == False:
                self.abort_run(reason="emergency_temp_too_high")

        if self.board.temp_sensor.status.over_error_limit():
            log.info("emergency!!! too many errors in a short period")
            self._notify_with_cooldown(
                key="tc_error_rate",
                event="issue_detected",
                payload={
                    "profile": self.profile.name if self.profile else None,
                    "run_id": self.current_run_id,
                    "issue": "thermocouple_error_rate_high",
                    "error_rate_pct": self.board.temp_sensor.status.error_percent(),
                },
                cooldown_seconds=60,
            )
            if config.ignore_tc_too_many_errors == False:
                self._notify_event(
                    "sensor_fault",
                    {
                        "error_rate_pct": self.board.temp_sensor.status.error_percent(),
                        "run_id": self.current_run_id,
                        "profile": self.profile.name if self.profile else None,
                    },
                )
                self.abort_run(reason="emergency_tc_error_rate")

    def reset_if_schedule_ended(self) -> None:
        """Finish the run when the schedule runtime has been exhausted."""
        if self.runtime > self.totaltime:
            log.info("schedule ended, shutting down")
            log.info("total cost = %s%.2f" % (config.currency_type, self.cost))
            self.abort_run(reason="schedule_complete")

    def update_cost(self) -> None:
        """Accumulate run cost based on the current commanded heat output."""
        if self.heat:
            cost = (config.kwh_rate * config.kw_elements) * ((self.heat) / 3600)
        else:
            cost = 0
        self.cost = self.cost + cost

    def get_state(self) -> dict[str, Any]:
        """Return the current oven state snapshot for APIs and websocket clients."""
        temp = 0
        try:
            temp = self.board.temp_sensor.temperature() + config.thermocouple_offset
        except AttributeError:
            # Simulated boards can briefly lack a sensor during startup.
            temp = 0
            pass
        except Exception as e:
            # Keep API state available even when a sensor read fails unexpectedly.
            log.error(f"Error reading temperature in get_state(): {e}")
            temp = 0

        self.set_heat_rate(self.runtime, temp)
        self.temperature = temp
        self._record_telemetry_sample(temp)

        state = {
            "cost": self.cost,
            "runtime": self.runtime,
            "temperature": temp,
            "target": self.target,
            "state": self.state,
            "heat": self.heat,
            "heat_rate": self.heat_rate,
            "totaltime": self.totaltime,
            "kwh_rate": config.kwh_rate,
            "currency_type": config.currency_type,
            "profile": self.profile.name if self.profile else None,
            "pidstats": self.pid.pidstats,
            "catching_up": self.catching_up,
            "telemetry": self.get_telemetry(),
            "last_run_summary": self.last_run_summary,
            "status_reason": self.last_run_summary.get("reason") if self.last_run_summary else None,
            "status_reason_text": (
                self.last_run_summary.get("reason_text") if self.last_run_summary else None
            ),
            "status_reason_kind": (
                self.last_run_summary.get("reason_kind") if self.last_run_summary else None
            ),
            "firing_record_file": self.current_firing_log_file,
        }
        return state

    def save_state(self) -> None:
        """Write the current oven state snapshot to the restart-state file."""
        with open(config.automatic_restart_state_file, "w", encoding="utf-8") as f:
            json.dump(self.get_state(), f, ensure_ascii=False, indent=4)

    def state_file_is_old(self) -> bool:
        """Return whether the automatic-restart state file is too old to trust."""
        if os.path.isfile(config.automatic_restart_state_file):
            state_age = os.path.getmtime(config.automatic_restart_state_file)
            now = time.time()
            minutes = (now - state_age) / 60
            if minutes <= config.automatic_restart_window:
                return False
        return True

    def save_automatic_restart_state(self) -> bool | None:
        """Persist automatic-restart state when the feature is enabled."""
        if not config.automatic_restarts == True:
            return False
        self.save_state()

    def should_i_automatic_restart(self) -> bool:
        """Return whether the previous state should be used for an automatic restart."""
        if not config.automatic_restarts == True:
            return False
        if self.state_file_is_old():
            duplog.info("automatic restart not possible. state file does not exist or is too old.")
            return False

        with open(config.automatic_restart_state_file) as infile:
            d = json.load(infile)
        if d["state"] != "RUNNING":
            duplog.info("automatic restart not possible. state = %s" % (d["state"]))
            return False
        return True

    def automatic_restart(self) -> None:
        """Resume the last recorded run from the persisted restart-state file."""
        with open(config.automatic_restart_state_file) as infile:
            d = json.load(infile)
        startat = d["runtime"] / 60
        filename = "%s.json" % (d["profile"])
        profile_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "storage", "profiles", filename)
        )

        log.info("automatically restarting profile = %s at minute = %d" % (profile_path, startat))
        with open(profile_path) as infile:
            profile_json = json.dumps(json.load(infile))
        profile = Profile(profile_json)
        # Automatic restart should resume from recorded runtime without seek-start.
        self.run_profile(profile, startat=startat, allow_seek=False)
        self.cost = d["cost"]
        time.sleep(1)
        self.ovenwatcher.record(profile)

    def set_ovenwatcher(self, watcher: Any) -> None:
        log.info("ovenwatcher set in oven class")
        self.ovenwatcher = watcher

    def set_notifier(self, notifier: Any) -> None:
        self.notifier = notifier

    def emit_notification(self, event: str, payload: dict[str, Any] | None = None) -> None:
        self._notify_event(event, payload)

    def _notify_event(self, event: str, payload: dict[str, Any] | None = None) -> None:
        if not self.notifier:
            return
        try:
            self.notifier.emit_event(event, payload or {})
        except Exception as exc:
            log.error("failed to queue notification event=%s: %s", event, exc)

    def run(self) -> None:
        while True:
            log.debug("Oven running on " + threading.current_thread().name)
            if self.state == "IDLE":
                if self.should_i_automatic_restart() == True:
                    self.automatic_restart()
                time.sleep(1)
                continue
            if self.state == "PAUSED":
                self.start_time = self.get_start_time()
                self.update_runtime()
                self.update_target_temp()
                self.heat_then_cool()
                self.reset_if_emergency()
                self.reset_if_schedule_ended()
                continue
            if self.state == "RUNNING":
                self.update_cost()
                self.save_automatic_restart_state()
                self.kiln_must_catch_up()
                self.update_runtime()
                self.update_target_temp()
                self.heat_then_cool()
                self.reset_if_emergency()
                self.reset_if_schedule_ended()


class SimulatedOven(Oven):
    def __init__(self) -> None:
        self.board = SimulatedBoard()
        self.t_env = config.sim_t_env
        self.c_heat = config.sim_c_heat
        self.c_oven = config.sim_c_oven
        self.p_heat = config.sim_p_heat
        self.R_o_nocool = config.sim_R_o_nocool
        self.R_ho_noair = config.sim_R_ho_noair
        self.R_ho = self.R_ho_noair
        self.speedup_factor = config.sim_speedup_factor

        # set temps to the temp of the surrounding environment
        self.t = config.sim_t_env  # deg C or F temp of oven
        self.t_h = self.t_env  # deg C temp of heating element

        super().__init__()

        self.start_time = self.get_start_time()

        # start thread
        self.start()
        log.info("SimulatedOven started")

    # runtime is in sped up time, start_time is actual time of day
    def get_start_time(self) -> datetime.datetime:
        return datetime.datetime.now() - datetime.timedelta(
            milliseconds=self.runtime * 1000 / self.speedup_factor
        )

    def update_runtime(self) -> None:
        runtime_delta = datetime.datetime.now() - self.start_time
        if runtime_delta.total_seconds() < 0:
            runtime_delta = datetime.timedelta(0)

        self.runtime = runtime_delta.total_seconds() * self.speedup_factor

    def update_target_temp(self) -> None:
        self.target = self.profile.get_target_temperature(self.runtime)

    def heating_energy(self, pid: float) -> None:
        # using pid here simulates the element being on for
        # only part of the time_step
        self.Q_h = self.p_heat * self.time_step * pid

    def temp_changes(self) -> None:
        # temperature change of heat element by heating
        self.t_h += self.Q_h / self.c_heat

        # energy flux heat_el -> oven
        self.p_ho = (self.t_h - self.t) / self.R_ho

        # temperature change of oven and heating element
        self.t += self.p_ho * self.time_step / self.c_oven
        self.t_h -= self.p_ho * self.time_step / self.c_heat

        # temperature change of oven by cooling to environment
        self.p_env = (self.t - self.t_env) / self.R_o_nocool
        self.t -= self.p_env * self.time_step / self.c_oven
        self.temperature = self.t
        self.board.temp_sensor.simulated_temperature = self.t

    def heat_then_cool(self) -> None:
        now_simulator = self.start_time + datetime.timedelta(milliseconds=self.runtime * 1000)
        cycle_epoch = time.time()
        pid = self.pid.compute(
            self.target,
            self.board.temp_sensor.temperature() + config.thermocouple_offset,
            now_simulator,
        )

        heat_on = float(self.time_step * pid)
        heat_off = float(self.time_step * (1 - pid))

        self.heating_energy(pid)
        self.temp_changes()

        # self.heat is for the front end to display if the heat is on
        self.heat = 0.0
        if heat_on > 0:
            self.heat = heat_on

        log.info(
            "simulation: -> %dW heater: %.0f -> %dW oven: %.0f -> %dW env"
            % (int(self.p_heat * pid), self.t_h, int(self.p_ho), self.t, int(self.p_env))
        )

        time_left = self.totaltime - self.runtime

        try:
            log.info(
                "temp=%.2f, target=%.2f, error=%.2f, pid=%.2f, p=%.2f, i=%.2f, d=%.2f, heat_on=%.2f, heat_off=%.2f, run_time=%d, total_time=%d, time_left=%d"
                % (
                    self.pid.pidstats["ispoint"],
                    self.pid.pidstats["setpoint"],
                    self.pid.pidstats["err"],
                    self.pid.pidstats["pid"],
                    self.pid.pidstats["p"],
                    self.pid.pidstats["i"],
                    self.pid.pidstats["d"],
                    heat_on,
                    heat_off,
                    self.runtime,
                    self.totaltime,
                    time_left,
                )
            )
        except KeyError:
            pass

        measured_temp = float(
            self.pid.pidstats.get(
                "ispoint",
                self.board.temp_sensor.temperature() + config.thermocouple_offset,
            )
        )
        self._record_firing_cycle(
            measured_temp=measured_temp,
            heat_on=heat_on,
            heat_off=heat_off,
            cycle_epoch=cycle_epoch,
            notes="simulation",
        )

        # we don't actually spend time heating & cooling during
        # a simulation, so sleep.
        time.sleep(self.time_step / self.speedup_factor)


class RealOven(Oven):
    def __init__(self, buzzer: Any | None = None) -> None:
        self.board = RealBoard()
        self.output = Output()
        self.reset()

        # call parent init
        Oven.__init__(self, buzzer)

        # start thread
        self.start()

    def reset(self) -> None:
        super().reset()
        self.output.cool(0)

    def heat_then_cool(self) -> None:
        cycle_epoch = time.time()
        pid = self.pid.compute(
            self.target,
            self.board.temp_sensor.temperature() + config.thermocouple_offset,
            datetime.datetime.now(),
        )

        heat_on = float(self.time_step * pid)
        heat_off = float(self.time_step * (1 - pid))

        # Minimum on-time protection: if heat_on is less than minimum,
        # round it down to 0 to prevent rapid cycling.
        # Exception: Allow throttled heating (intentional low power operation)
        # to bypass the minimum to prevent blocking legitimate throttling.
        # Throttling occurs when: target <= throttle_below_temp, error is large (outside PID window),
        # and PID output matches throttle percentage.
        current_temp = self.board.temp_sensor.temperature() + config.thermocouple_offset
        error = self.target - current_temp
        is_throttled = (
            config.throttle_below_temp
            and config.throttle_percent
            and self.target <= config.throttle_below_temp
            and error > config.pid_control_window
            and abs(pid - (config.throttle_percent / 100.0)) < 0.01
        )
        cycle_notes = []

        if config.min_on_time > 0 and 0 < heat_on < config.min_on_time and not is_throttled:
            log.debug(
                f"heat_on ({heat_on:.3f}s) below minimum ({config.min_on_time}s), setting to 0"
            )
            heat_off = self.time_step  # entire cycle is off
            heat_on = 0.0
            cycle_notes.append("min_on_time_clamped")
        if is_throttled:
            cycle_notes.append("throttled")

        # self.heat is for the front end to display if the heat is on
        self.heat = 0.0
        if heat_on > 0:
            self.heat = 1.0

        if heat_on:
            self.output.heat(heat_on)
        if heat_off:
            self.output.cool(heat_off)
        time_left = self.totaltime - self.runtime
        power = self._get_power_snapshot()
        line_current = power.get("current")
        line_power = power.get("power")
        line_voltage = power.get("voltage")
        current_txt = "%.3f" % float(line_current) if line_current is not None else "--"
        power_txt = "%.1f" % float(line_power) if line_power is not None else "--"
        voltage_txt = "%.1f" % float(line_voltage) if line_voltage is not None else "--"
        try:
            log.info(
                "temp=%.2f, target=%.2f, error=%.2f, pid=%.2f, p=%.2f, i=%.2f, d=%.2f, heat_on=%.2f, heat_off=%.2f, run_time=%d, total_time=%d, time_left=%d, line_v=%s, line_i=%s, line_p=%s"
                % (
                    self.pid.pidstats["ispoint"],
                    self.pid.pidstats["setpoint"],
                    self.pid.pidstats["err"],
                    self.pid.pidstats["pid"],
                    self.pid.pidstats["p"],
                    self.pid.pidstats["i"],
                    self.pid.pidstats["d"],
                    heat_on,
                    heat_off,
                    self.runtime,
                    self.totaltime,
                    time_left,
                    voltage_txt,
                    current_txt,
                    power_txt,
                )
            )
        except KeyError:
            pass

        self._record_firing_cycle(
            measured_temp=current_temp,
            heat_on=heat_on,
            heat_off=heat_off,
            cycle_epoch=cycle_epoch,
            notes=",".join(cycle_notes),
        )


class Profile:
    """Represents a kiln profile loaded from JSON schedule data."""

    def __init__(self, json_data: str) -> None:
        obj = json.loads(json_data)
        self.name = obj["name"]
        self.data = sorted(obj["data"])

    def get_duration(self) -> float:
        return max([t for (t, x) in self.data])

    #  x = (y-y1)(x2-x1)/(y2-y1) + x1
    @staticmethod
    def find_x_given_y_on_line_from_two_points(
        y: float, point1: Sequence[float], point2: Sequence[float]
    ) -> float:
        if point1[0] > point2[0]:
            return 0  # time2 before time1 makes no sense in kiln segment
        if point1[1] >= point2[1]:
            return 0  # Zero will crach. Negative temeporature slope, we don't want to seek a time.
        x = (y - point1[1]) * (point2[0] - point1[0]) / (point2[1] - point1[1]) + point1[0]
        return x

    def find_next_time_from_temperature(self, temperature: float) -> float:
        time = 0  # The seek function will not do anything if this returns zero, no useful intersection was found
        for index, point2 in enumerate(self.data):
            if point2[1] >= temperature:
                if index > 0:  #  Zero here would be before the first segment
                    if self.data[index - 1][1] <= temperature:  # We have an intersection
                        time = self.find_x_given_y_on_line_from_two_points(
                            temperature, self.data[index - 1], point2
                        )
                        if time == 0:
                            if (
                                self.data[index - 1][1] == point2[1]
                            ):  # It's a flat segment that matches the temperature
                                time = self.data[index - 1][0]
                                break

        return time

    def get_surrounding_points(self, time):
        if time > self.get_duration():
            return (None, None)

        prev_point = None
        next_point = None

        for i in range(len(self.data)):
            if time < self.data[i][0]:
                prev_point = self.data[i - 1]
                next_point = self.data[i]
                break

        return (prev_point, next_point)

    def get_target_temperature(self, time):
        if time > self.get_duration():
            return 0

        (prev_point, next_point) = self.get_surrounding_points(time)

        incl = float(next_point[1] - prev_point[1]) / float(next_point[0] - prev_point[0])
        temp = prev_point[1] + (time - prev_point[0]) * incl
        return temp


class PID:
    def __init__(self, ki=1, kp=1, kd=1):
        self.ki = ki
        self.kp = kp
        self.kd = kd
        self.lastNow = datetime.datetime.now()
        self.iterm = 0
        self.lastErr = 0
        self.pidstats = {}

    # FIX - this was using a really small window where the PID control
    # takes effect from -1 to 1. I changed this to various numbers and
    # settled on -50 to 50 and then divide by 50 at the end. This results
    # in a larger PID control window and much more accurate control...
    # instead of what used to be binary on/off control.
    def compute(self, setpoint, ispoint, now):
        timeDelta = (now - self.lastNow).total_seconds()

        window_size = 100

        error = float(setpoint - ispoint)

        # this removes the need for config.stop_integral_windup
        # it turns the controller into a binary on/off switch
        # any time it's outside the window defined by
        # config.pid_control_window
        icomp = 0
        output = 0
        out4logs = 0
        dErr = 0
        if error < (-1 * config.pid_control_window):
            log.info("kiln outside pid control window, max cooling")
            output = 0
            # it is possible to set self.iterm=0 here and also below
            # but I dont think its needed
        elif error > (1 * config.pid_control_window):
            log.info("kiln outside pid control window, max heating")
            output = 1
            if config.throttle_below_temp and config.throttle_percent:
                if setpoint <= config.throttle_below_temp:
                    output = config.throttle_percent / 100
                    log.info(
                        "max heating throttled at %d percent below %d degrees to prevent overshoot"
                        % (config.throttle_percent, config.throttle_below_temp)
                    )
        else:
            icomp = error * timeDelta * (1 / self.ki)
            self.iterm += error * timeDelta * (1 / self.ki)
            dErr = (error - self.lastErr) / timeDelta
            output = self.kp * error + self.iterm + self.kd * dErr
            output = sorted([-1 * window_size, output, window_size])[1]
            out4logs = output
            output = float(output / window_size)

        self.lastErr = error
        self.lastNow = now

        # no active cooling
        if output < 0:
            output = 0

        self.pidstats = {
            "time": time.mktime(now.timetuple()),
            "timeDelta": timeDelta,
            "setpoint": setpoint,
            "ispoint": ispoint,
            "err": error,
            "errDelta": dErr,
            "p": self.kp * error,
            "i": self.iterm,
            "d": self.kd * dErr,
            "kp": self.kp,
            "ki": self.ki,
            "kd": self.kd,
            "pid": out4logs,
            "out": output,
        }

        return output
