"""Unit tests for controller storage and helper hardening."""

from __future__ import annotations

import io
import json
from pathlib import Path
from wsgiref.util import setup_testing_defaults

import config
import pytest

from thekilngod import controller
from thekilngod.oven import Oven


def _profile_payload(name: str) -> dict[str, object]:
    return {
        "name": name,
        "data": [[0, 75], [600, 250]],
    }


def _request_app(
    *,
    path: str,
    method: str = "GET",
    body: bytes = b"",
    content_type: str = "application/json",
    cookie: str | None = None,
) -> tuple[str, bytes]:
    status, _headers, payload = _request_app_full(
        path=path,
        method=method,
        body=body,
        content_type=content_type,
        cookie=cookie,
    )
    return status, payload


def _request_app_full(
    *,
    path: str,
    method: str = "GET",
    body: bytes = b"",
    content_type: str = "application/json",
    cookie: str | None = None,
) -> tuple[str, list[tuple[str, str]], bytes]:
    environ: dict[str, object] = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    environ["CONTENT_TYPE"] = content_type
    environ["CONTENT_LENGTH"] = str(len(body))
    environ["wsgi.input"] = io.BytesIO(body)
    if cookie:
        environ["HTTP_COOKIE"] = cookie

    captured: dict[str, str] = {}
    captured_headers: list[tuple[str, str]] = []

    def start_response(
        status: str,
        headers: list[tuple[str, str]],
        exc_info: object | None = None,
    ) -> None:
        captured["status"] = status
        captured_headers.extend(headers)

    payload = b"".join(controller.app(environ, start_response))
    return captured["status"], captured_headers, payload


def test_controller_import_is_lazy() -> None:
    """Importing the controller module should not build runtime dependencies."""
    assert controller._runtime is None


def test_profile_file_path_rejects_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profile helper should refuse unsafe names before touching the filesystem."""
    monkeypatch.setattr(controller, "PROFILE_ROOT", tmp_path.resolve())

    assert controller._profile_file_path("../secrets") is None
    assert controller._profile_file_path("nested/name") is None
    assert controller._profile_file_path("..\\windows") is None


def test_save_profile_respects_force_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing profiles should be protected unless force=True is supplied."""
    monkeypatch.setattr(controller, "PROFILE_ROOT", tmp_path.resolve())

    ok, error = controller.save_profile(_profile_payload("cone-6"), force=False)
    assert ok is True
    assert error is None

    ok, error = controller.save_profile(_profile_payload("cone-6"), force=False)
    assert ok is False
    assert error == "Profile exists"

    ok, error = controller.save_profile(_profile_payload("cone-6"), force=True)
    assert ok is True
    assert error is None


def test_delete_profile_rejects_invalid_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delete helper should refuse invalid or escaping profile names."""
    monkeypatch.setattr(controller, "PROFILE_ROOT", tmp_path.resolve())

    ok, error = controller.delete_profile({"name": "../config"})
    assert ok is False
    assert error == "invalid profile name"


def test_load_profiles_ignores_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed JSON files should not break profile listing."""
    monkeypatch.setattr(controller, "PROFILE_ROOT", tmp_path.resolve())

    good_path = tmp_path / "valid.json"
    bad_path = tmp_path / "broken.json"
    good_path.write_text(json.dumps(_profile_payload("cone-04")), encoding="utf-8")
    bad_path.write_text("{not json", encoding="utf-8")

    profiles = controller._load_profiles_from_disk()
    assert [profile["name"] for profile in profiles] == ["cone-04"]


def test_scale_power_value_uses_config_factor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live power values should be scaled the same way as run aggregates."""
    monkeypatch.setattr(config, "power_sensor_scale_factor", 2.0)

    assert Oven._scale_power_value(12.5) == 25.0
    assert Oven._scale_power_value(None) is None


def test_get_config_exposes_hardware_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    """UI config payload should include JSON-safe hardware inspection fields."""

    class _FakePin:
        def __init__(self, label: str) -> None:
            self.label = label

        def __str__(self) -> str:
            return self.label

    monkeypatch.setattr(config, "gpio_heat", _FakePin("board.D16"), raising=False)
    monkeypatch.setattr(config, "gpio_heat_invert", True, raising=False)
    monkeypatch.setattr(config, "gpio_buzzer", 12, raising=False)
    monkeypatch.setattr(config, "spi_sclk", _FakePin("board.D23"), raising=False)
    monkeypatch.setattr(config, "spi_miso", _FakePin("board.D21"), raising=False)
    monkeypatch.setattr(config, "spi_mosi", _FakePin("board.D19"), raising=False)
    monkeypatch.setattr(config, "spi_cs", _FakePin("board.D24"), raising=False)
    monkeypatch.setattr(config, "display_i2c_address", 0x3C, raising=False)
    monkeypatch.setattr(config, "power_sensor_enabled", True, raising=False)
    monkeypatch.setattr(config, "power_sensor_port", "/dev/ttyUSB0", raising=False)

    payload = json.loads(controller.get_config())

    assert payload["temp_scale"] == config.temp_scale
    assert payload["hardware"]["relay"] == {
        "gpio_heat": "board.D16",
        "gpio_heat_invert": True,
    }
    assert payload["hardware"]["buzzer"] == {"gpio_buzzer": 12}
    assert payload["hardware"]["spi"]["mode"] == "software"
    assert payload["hardware"]["spi"]["spi_cs"] == "board.D24"
    assert payload["hardware"]["display"]["i2c_address"] == "0x3c"
    assert payload["hardware"]["power_sensor"]["enabled"] is True
    assert payload["hardware"]["power_sensor"]["port"] == "/dev/ttyUSB0"


def test_post_api_requires_json_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed or empty POST bodies should fail before runtime initialization."""

    def _unexpected_runtime() -> object:
        raise AssertionError("runtime should not initialize for invalid request bodies")

    monkeypatch.setattr(controller, "get_runtime", _unexpected_runtime)

    status, payload = _request_app(path="/api", method="POST", body=b"")

    assert status.startswith("400")
    assert json.loads(payload)["error"] == "request body must be a JSON object"


def test_post_api_rejects_missing_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing command should produce a stable 400 response."""

    def _unexpected_runtime() -> object:
        raise AssertionError("runtime should not initialize for missing cmd")

    monkeypatch.setattr(controller, "get_runtime", _unexpected_runtime)

    status, payload = _request_app(path="/api", method="POST", body=b"{}")

    assert status.startswith("400")
    assert json.loads(payload)["error"] == "cmd is required"


def test_post_api_rejects_unknown_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown commands should be rejected cleanly without touching runtime state."""

    def _unexpected_runtime() -> object:
        raise AssertionError("runtime should not initialize for unknown commands")

    monkeypatch.setattr(controller, "get_runtime", _unexpected_runtime)

    status, payload = _request_app(
        path="/api",
        method="POST",
        body=json.dumps({"cmd": "unknown"}).encode("utf-8"),
    )

    assert status.startswith("400")
    assert json.loads(payload)["error"] == "unknown cmd: unknown"


def test_status_http_request_returns_400_before_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """WebSocket endpoints should reject plain HTTP without booting the runtime."""

    def _unexpected_runtime() -> object:
        raise AssertionError("runtime should not initialize for plain HTTP status requests")

    monkeypatch.setattr(controller, "get_runtime", _unexpected_runtime)

    status, _payload = _request_app(path="/status", method="GET", content_type="text/plain")

    assert status.startswith("400")


def test_ui_auth_status_disabled_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """UI auth should stay disabled when no environment variable is configured."""
    monkeypatch.delenv("KILN_UI_PASSWORD", raising=False)

    status, payload = _request_app(path="/ui-auth/status", method="GET", content_type="text/plain")

    assert status.startswith("200")
    assert json.loads(payload) == {"success": True, "enabled": False, "unlocked": True}


def test_ui_auth_unlock_sets_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    """Correct UI password should unlock the browser session with a cookie."""
    monkeypatch.setenv("KILN_UI_PASSWORD", "kiln123")

    status, headers, payload = _request_app_full(
        path="/ui-auth/unlock",
        method="POST",
        body=json.dumps({"password": "kiln123"}).encode("utf-8"),
    )

    assert status.startswith("200")
    assert json.loads(payload)["unlocked"] is True
    set_cookie = next(value for key, value in headers if key.lower() == "set-cookie")
    assert controller.UI_UNLOCK_COOKIE in set_cookie

    cookie = set_cookie.split(";", 1)[0]
    status, payload = _request_app(path="/ui-auth/status", method="GET", cookie=cookie)
    assert status.startswith("200")
    assert json.loads(payload)["unlocked"] is True


def test_ui_auth_unlock_rejects_bad_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Incorrect UI password should not unlock the session."""
    monkeypatch.setenv("KILN_UI_PASSWORD", "kiln123")

    status, payload = _request_app(
        path="/ui-auth/unlock",
        method="POST",
        body=json.dumps({"password": "wrong"}).encode("utf-8"),
    )

    assert status.startswith("401")
    assert json.loads(payload)["error"] == "incorrect password"
