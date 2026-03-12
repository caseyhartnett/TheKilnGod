"""Power sensor readers for live kiln telemetry."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from contextlib import suppress
from typing import Any

try:
    import serial
except ImportError:  # pragma: no cover - depends on runtime environment
    serial = None

log = logging.getLogger(__name__)


def _crc16_modbus(payload: bytes) -> int:
    """Return Modbus RTU CRC16 for a payload."""
    crc = 0xFFFF
    for b in payload:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def _safe_float(value: Any) -> float | None:
    """Convert numeric-ish values to float, returning None for invalid values."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n:  # NaN check without math import
        return None
    return n


class NullPowerSensor:
    """No-op power sensor used when the hardware reader is disabled or unavailable."""

    def __init__(self, reason: str = "disabled") -> None:
        """Store the reason this placeholder sensor is unavailable."""
        self.reason = reason

    def start(self) -> None:
        """No background thread required."""

    def stop(self) -> None:
        """No background thread required."""

    def snapshot(self) -> dict[str, Any]:
        """Return an unavailable sensor snapshot."""
        return {
            "available": False,
            "ok": False,
            "stale": True,
            "reason": self.reason,
            "last_update": None,
            "error_rate_pct": 100.0,
            "voltage": None,
            "current": None,
            "power": None,
            "energy_wh": None,
            "frequency_hz": None,
            "power_factor": None,
        }


class Pzem004tPowerSensor(threading.Thread):
    """Background reader for PZEM-004T (Modbus RTU over UART)."""

    RESPONSE_LEN = 25

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        address: int = 1,
        poll_interval: float = 2.0,
        timeout: float = 0.4,
        stale_seconds: float = 10.0,
    ) -> None:
        """Initialize UART polling settings and in-memory sensor state."""
        if serial is None:
            raise RuntimeError("pyserial is not installed")
        super().__init__(daemon=True, name="pzem004t-reader")
        self.port = port
        self.baudrate = int(baudrate)
        self.address = int(address)
        self.poll_interval = max(0.2, float(poll_interval))
        self.timeout = max(0.05, float(timeout))
        self.stale_seconds = max(1.0, float(stale_seconds))
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._serial: serial.Serial | None = None

        self._last_update: float | None = None
        self._voltage: float | None = None
        self._current: float | None = None
        self._power: float | None = None
        self._energy_wh: float | None = None
        self._frequency_hz: float | None = None
        self._power_factor: float | None = None
        self._status: deque[bool] = deque(maxlen=120)
        self._last_error: str | None = None

    @staticmethod
    def build_read_frame(address: int) -> bytes:
        """Build a Modbus request frame to read PZEM input registers 0x0000..0x0009."""
        frame = bytes([address & 0xFF, 0x04, 0x00, 0x00, 0x00, 0x0A])
        crc = _crc16_modbus(frame)
        return frame + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    @staticmethod
    def parse_response(response: bytes, address: int) -> dict[str, float]:
        """Parse PZEM response bytes and return normalized measurements."""
        if len(response) != Pzem004tPowerSensor.RESPONSE_LEN:
            raise ValueError(f"unexpected response length {len(response)}")
        if response[0] != (address & 0xFF):
            raise ValueError("response address mismatch")
        if response[1] != 0x04:
            raise ValueError("unexpected function code")
        if response[2] != 0x14:
            raise ValueError("unexpected byte count")

        crc_expected = int.from_bytes(response[-2:], byteorder="little", signed=False)
        crc_actual = _crc16_modbus(response[:-2])
        if crc_actual != crc_expected:
            raise ValueError("bad CRC")

        data = response[3:23]
        regs = [
            int.from_bytes(data[i : i + 2], byteorder="big", signed=False) for i in range(0, 20, 2)
        ]
        voltage = regs[0] / 10.0
        current = ((regs[1] << 16) | regs[2]) / 1000.0
        power = ((regs[3] << 16) | regs[4]) / 10.0
        energy_wh = float((regs[5] << 16) | regs[6])
        frequency_hz = regs[7] / 10.0
        power_factor = regs[8] / 100.0
        return {
            "voltage": voltage,
            "current": current,
            "power": power,
            "energy_wh": energy_wh,
            "frequency_hz": frequency_hz,
            "power_factor": power_factor,
        }

    def _mark_status(self, ok: bool, error: str | None = None) -> None:
        with self._lock:
            self._status.append(bool(ok))
            self._last_error = error

    def _open_serial_if_needed(self) -> None:
        if self._serial and self._serial.is_open:
            return
        self._serial = serial.Serial(  # type: ignore[union-attr]
            port=self.port,
            baudrate=self.baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=self.timeout,
        )

    def _close_serial(self) -> None:
        if self._serial:
            with suppress(Exception):
                self._serial.close()
        self._serial = None

    def _poll_once(self) -> None:
        self._open_serial_if_needed()
        if not self._serial:
            raise RuntimeError("serial port unavailable")

        frame = self.build_read_frame(self.address)
        self._serial.reset_input_buffer()
        self._serial.write(frame)
        response = self._serial.read(self.RESPONSE_LEN)
        values = self.parse_response(response, self.address)

        with self._lock:
            self._last_update = time.time()
            self._voltage = _safe_float(values["voltage"])
            self._current = _safe_float(values["current"])
            self._power = _safe_float(values["power"])
            self._energy_wh = _safe_float(values["energy_wh"])
            self._frequency_hz = _safe_float(values["frequency_hz"])
            self._power_factor = _safe_float(values["power_factor"])
        self._mark_status(True, None)

    def run(self) -> None:
        """Poll the sensor until stop is requested, tracking failures in-memory."""
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                self._mark_status(False, str(exc))
                self._close_serial()
                log.debug("power sensor read failed: %s", exc)
            self._stop_event.wait(self.poll_interval)

        self._close_serial()

    def stop(self) -> None:
        """Request stop for the background thread."""
        self._stop_event.set()

    def snapshot(self) -> dict[str, Any]:
        """Return the latest sensor state and values."""
        with self._lock:
            update = self._last_update
            stale = True
            if update is not None:
                stale = (time.time() - update) > self.stale_seconds
            errors = sum(1 for item in self._status if not item)
            total = len(self._status)
            error_rate = (errors / total) * 100.0 if total else 0.0
            return {
                "available": True,
                "ok": update is not None and not stale,
                "stale": stale,
                "reason": self._last_error,
                "last_update": update,
                "error_rate_pct": error_rate,
                "voltage": self._voltage,
                "current": self._current,
                "power": self._power,
                "energy_wh": self._energy_wh,
                "frequency_hz": self._frequency_hz,
                "power_factor": self._power_factor,
            }
