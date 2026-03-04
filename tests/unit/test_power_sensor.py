"""Unit tests for PZEM power sensor frame handling."""

from thekilngod.power_sensor import Pzem004tPowerSensor


def _crc16_modbus(payload: bytes) -> int:
    crc = 0xFFFF
    for b in payload:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def test_build_read_frame_contains_valid_crc() -> None:
    """Read frame should be fixed-shape and parseable by CRC checks downstream."""
    frame = Pzem004tPowerSensor.build_read_frame(1)
    assert len(frame) == 8
    assert frame[:6] == bytes([0x01, 0x04, 0x00, 0x00, 0x00, 0x0A])


def test_parse_response_decodes_fields() -> None:
    """Parser should decode register payload into engineering units."""
    # Registers:
    # V=240.1, I=12.345, P=1234.5, E=54321, F=60.0, PF=0.98, alarm=0
    regs = [
        2401,
        0,
        12345,
        0,
        12345,
        0,
        54321,
        600,
        98,
        0,
    ]
    data = b"".join(int(v).to_bytes(2, "big", signed=False) for v in regs)
    payload = bytes([0x01, 0x04, 0x14]) + data
    crc = _crc16_modbus(payload)
    frame = payload + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    parsed = Pzem004tPowerSensor.parse_response(frame, 1)
    assert parsed["voltage"] == 240.1
    assert parsed["current"] == 12.345
    assert parsed["power"] == 1234.5
    assert parsed["energy_wh"] == 54321.0
    assert parsed["frequency_hz"] == 60.0
    assert parsed["power_factor"] == 0.98


def test_parse_response_rejects_bad_crc() -> None:
    """Parser should raise for frames with invalid checksums."""
    bad_frame = bytes([0x01, 0x04, 0x14]) + bytes(20) + bytes([0x00, 0x00])
    try:
        Pzem004tPowerSensor.parse_response(bad_frame, 1)
    except ValueError as exc:
        assert "CRC" in str(exc)
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("expected ValueError for bad CRC")
