#!/usr/bin/env python
"""HTTP and WebSocket API layer for kiln control and monitoring."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

import bottle

# Import config eagerly so setup and hardware errors fail fast at startup.
import config

from gevent.pywsgi import WSGIServer
from geventwebsocket import WebSocketError
from geventwebsocket.handler import WebSocketHandler

logging.basicConfig(level=config.log_level, format=config.log_format)
log = logging.getLogger("kiln-controller")
log.info("Starting kiln controller")
log.info(
    "GPIO config: heat_pin=%s heat_invert=%s buzzer_pin=%s simulate=%s",
    getattr(config, "gpio_heat", None),
    getattr(config, "gpio_heat_invert", None),
    getattr(config, "gpio_buzzer", None),
    getattr(config, "simulate", None),
)

profile_path = config.kiln_profiles_directory
PROFILE_ROOT = Path(profile_path).resolve()
PROFILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")

from .buzzer import Buzzer
from .display_updater import DisplayUpdater
from .homeassistant_mqtt import HomeAssistantMQTT
from .notifications import NotificationManager
from .oven import Profile, RealOven, SimulatedOven
from .oven_watcher import OvenWatcher

app = bottle.Bottle()
_runtime: ControllerRuntime | None = None
UI_PASSWORD_ENV = "KILN_UI_PASSWORD"
UI_UNLOCK_COOKIE = "kiln_ui_unlock"


@dataclass
class ControllerRuntime:
    """Stateful controller dependencies initialized at runtime startup."""

    oven: RealOven | SimulatedOven
    notifier: NotificationManager
    oven_watcher: OvenWatcher
    buzzer: Buzzer | None
    display_updater: DisplayUpdater | None
    homeassistant_mqtt: HomeAssistantMQTT | None


def build_runtime() -> ControllerRuntime:
    """Create and wire the kiln runtime only when the server actually starts."""
    buzzer = None
    if not config.simulate:
        try:
            buzzer = Buzzer()
        except Exception as exc:
            log.warning("Failed to initialize buzzer: %s", exc)

    if config.simulate is True:
        log.info("this is a simulation")
        oven = SimulatedOven()
    else:
        log.info("this is a real kiln")
        oven = RealOven(buzzer=buzzer)

    notifier = NotificationManager()
    notifier.start()
    oven.set_notifier(notifier)

    oven_watcher = OvenWatcher(oven)
    oven.set_ovenwatcher(oven_watcher)

    display_updater = None
    if getattr(config, "display_enabled", True):
        display_updater = DisplayUpdater(oven, update_interval=2.0)
        display_updater.start()
        log.info("Display updater started")
    else:
        log.info("Display disabled in config")

    homeassistant_mqtt = None
    if getattr(config, "ha_mqtt_enabled", False):
        homeassistant_mqtt = HomeAssistantMQTT(oven)
        homeassistant_mqtt.start()
        log.info("Home Assistant MQTT updater started")
    else:
        log.info("Home Assistant MQTT disabled in config")

    return ControllerRuntime(
        oven=oven,
        notifier=notifier,
        oven_watcher=oven_watcher,
        buzzer=buzzer,
        display_updater=display_updater,
        homeassistant_mqtt=homeassistant_mqtt,
    )


def get_runtime() -> ControllerRuntime:
    """Return the shared runtime, initializing it lazily on first use."""
    global _runtime
    if _runtime is None:
        _runtime = build_runtime()
    return _runtime


def _coerce_profile_name(value: object) -> str | None:
    """Return a validated profile name or None if it is unsafe."""
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name or not PROFILE_NAME_PATTERN.fullmatch(name):
        return None
    if ".." in name or "/" in name or "\\" in name:
        return None
    return name


def _profile_file_path(name: object) -> Path | None:
    """Resolve a validated profile path within the configured profile root."""
    profile_name = _coerce_profile_name(name)
    if profile_name is None:
        return None
    candidate = (PROFILE_ROOT / f"{profile_name}.json").resolve()
    try:
        candidate.relative_to(PROFILE_ROOT)
    except ValueError:
        return None
    return candidate


def _load_profiles_from_disk() -> list[dict[str, Any]]:
    """Load JSON profiles from storage, ignoring malformed entries."""
    try:
        files = sorted(PROFILE_ROOT.glob("*.json"))
    except OSError:
        return []

    profiles: list[dict[str, Any]] = []
    for path in files:
        try:
            with path.open(encoding="utf-8") as f:
                obj = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Skipping unreadable profile %s: %s", path, exc)
            continue
        if isinstance(obj, dict):
            profiles.append(obj)
    return normalize_temp_units(profiles)


def _parse_api_body() -> dict[str, Any] | None:
    """Return a validated JSON object body for the POST /api endpoint."""
    body = bottle.request.json
    if not isinstance(body, dict):
        bottle.response.status = 400
        return {"success": False, "error": "request body must be a JSON object"}
    cmd = body.get("cmd")
    if not isinstance(cmd, str) or not cmd.strip():
        bottle.response.status = 400
        return {"success": False, "error": "cmd is required"}
    return body


def get_ui_password() -> str | None:
    """Return the optional shared UI password from the environment."""
    password = os.environ.get(UI_PASSWORD_ENV, "").strip()
    return password or None


def _ui_unlock_cookie_value(password: str) -> str:
    """Derive a stable session cookie value from the configured UI password."""
    return hmac.new(
        password.encode("utf-8"),
        b"thekilngod-ui-v2-unlock",
        hashlib.sha256,
    ).hexdigest()


def ui_password_enabled() -> bool:
    """Return whether ui-v2 password protection is enabled."""
    return get_ui_password() is not None


def ui_unlocked() -> bool:
    """Return whether the current browser session has unlocked ui-v2."""
    password = get_ui_password()
    if password is None:
        return True
    cookie = bottle.request.get_cookie(UI_UNLOCK_COOKIE)
    if not cookie:
        return False
    return hmac.compare_digest(cookie, _ui_unlock_cookie_value(password))


def set_ui_unlock_cookie() -> None:
    """Mark the current browser session as unlocked for ui-v2."""
    password = get_ui_password()
    if password is None:
        return
    bottle.response.set_cookie(
        UI_UNLOCK_COOKIE,
        _ui_unlock_cookie_value(password),
        path="/",
        httponly=True,
        samesite="Lax",
    )


def clear_ui_unlock_cookie() -> None:
    """Clear the current browser ui-v2 unlock session."""
    bottle.response.delete_cookie(UI_UNLOCK_COOKIE, path="/")


def get_request_token():
    """Return the API token from the request header or query string."""
    token = bottle.request.get_header("X-API-Token")
    if not token:
        token = bottle.request.query.get("token")
    return token


def get_token_role(token):
    """Map a presented token to its effective authorization role."""
    monitor_token = getattr(config, "api_monitor_token", None)
    control_token = getattr(config, "api_control_token", None)
    if control_token and token == control_token:
        return "control"
    if monitor_token and token == monitor_token:
        return "monitor"
    if not monitor_token and not control_token:
        return "open"
    return "invalid"


def control_authorized():
    """Return whether the request is allowed to issue control commands."""
    monitor_token = getattr(config, "api_monitor_token", None)
    control_token = getattr(config, "api_control_token", None)
    got = get_request_token()

    if control_token:
        return got == control_token
    if monitor_token:
        return got == monitor_token
    return True


def monitor_authorized():
    """Return whether the request is allowed to read monitor endpoints."""
    monitor_token = getattr(config, "api_monitor_token", None)
    control_token = getattr(config, "api_control_token", None)
    got = get_request_token()

    if monitor_token:
        return got == monitor_token or (control_token and got == control_token)
    if control_token:
        return got == control_token
    return True


def deny_http_unauthorized():
    """Return a standard 401 JSON response for unauthorized HTTP requests."""
    bottle.response.status = 401
    return {"success": False, "error": "unauthorized"}


def deny_ws_unauthorized(wsock):
    """Send an unauthorized error to a websocket client and close it."""
    try:
        wsock.send(json.dumps({"success": False, "error": "unauthorized"}))
    except Exception:
        pass
    try:
        wsock.close()
    except Exception:
        pass


def load_run_health_exclusions():
    """Load the persisted set of excluded run identifiers."""
    path = getattr(config, "run_health_exclusions_file", None)
    if not path:
        return set()
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, list):
            return set(str(x) for x in obj)
        return set()
    except Exception as exc:
        log.error("failed reading run health exclusions: %s", exc)
        return set()


def save_run_health_exclusions(exclusions):
    """Persist the excluded run identifiers to disk."""
    path = getattr(config, "run_health_exclusions_file", None)
    if not path:
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(list(exclusions)), f, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:
        log.error("failed writing run health exclusions: %s", exc)
        return False


def load_run_health_rows(limit=1000):
    """Load recent run-health summary rows from the JSONL history file."""
    path = getattr(config, "run_health_history_file", None)
    rows = []
    if not path or not os.path.exists(path):
        return rows
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        rows.append(row)
                except json.JSONDecodeError:
                    continue
    except Exception as exc:
        log.error("failed reading run health history: %s", exc)
        return []
    if limit and len(rows) > limit:
        rows = rows[-1 * limit :]
    return rows


def audit_command(action, authorized, source="http", details=None):
    """Append one command-audit entry when auditing is enabled."""
    if not getattr(config, "command_audit_enabled", True):
        return
    if details is None:
        details = {}
    token = get_request_token()
    role = get_token_role(token)
    client = bottle.request.remote_addr or bottle.request.environ.get("REMOTE_ADDR") or "unknown"
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": source,
        "action": action,
        "authorized": bool(authorized),
        "role": role,
        "client": client,
        "details": details,
    }
    try:
        os.makedirs(os.path.dirname(config.command_audit_log_file), exist_ok=True)
        with open(config.command_audit_log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        log.error("failed to write audit log: %s", exc)


@app.get("/api/run-health")
def handle_run_health_get():
    if not monitor_authorized():
        return deny_http_unauthorized()
    try:
        limit = int(bottle.request.query.get("limit", "100"))
    except ValueError:
        limit = 100
    limit = max(1, min(5000, limit))

    include_excluded = str(bottle.request.query.get("include_excluded", "0")).lower() in (
        "1",
        "true",
        "yes",
    )
    exclusions = load_run_health_exclusions()
    rows = load_run_health_rows(limit=limit)

    out = []
    for row in rows:
        run_id = str(row.get("run_id", ""))
        excluded = run_id in exclusions if run_id else False
        row_out = dict(row)
        row_out["excluded"] = excluded
        if include_excluded or not excluded:
            out.append(row_out)

    return {
        "success": True,
        "rows": out,
        "exclusions": sorted(list(exclusions)),
        "returned": len(out),
        "limit": limit,
    }


@app.post("/api/run-health/exclusions")
def handle_run_health_exclusions():
    if not control_authorized():
        return deny_http_unauthorized()

    body = bottle.request.json or {}
    run_id = body.get("run_id")
    excluded = bool(body.get("excluded", True))
    if not run_id:
        bottle.response.status = 400
        return {"success": False, "error": "run_id is required"}

    exclusions = load_run_health_exclusions()
    run_id = str(run_id)
    if excluded:
        exclusions.add(run_id)
    else:
        exclusions.discard(run_id)

    if not save_run_health_exclusions(exclusions):
        bottle.response.status = 500
        return {"success": False, "error": "failed to save exclusions"}
    audit_command(
        "run_health_exclusion_set",
        True,
        source="http",
        details={"run_id": run_id, "excluded": excluded},
    )
    return {"success": True, "run_id": run_id, "excluded": excluded}


@app.route("/")
def index():
    """Redirect the root URL to the legacy dashboard."""
    return bottle.redirect("/picoreflow/index.html")


@app.route("/state")
def state():
    """Redirect the short state URL to the hosted state page."""
    return bottle.redirect("/picoreflow/state.html")


@app.route("/v2")
def v2():
    """Redirect the short v2 URL to the hosted ui-v2 bundle."""
    return bottle.redirect("/picoreflow/v2/index.html")


@app.get("/ui-auth/status")
def handle_ui_auth_status():
    """Return whether the optional UI password gate is enabled and unlocked."""
    return {
        "success": True,
        "enabled": ui_password_enabled(),
        "unlocked": ui_unlocked(),
    }


@app.post("/ui-auth/unlock")
def handle_ui_auth_unlock():
    """Unlock the UI for the current browser session."""
    password = get_ui_password()
    if password is None:
        return {
            "success": True,
            "enabled": False,
            "unlocked": True,
        }

    body = bottle.request.json
    if not isinstance(body, dict):
        bottle.response.status = 400
        return {"success": False, "error": "request body must be a JSON object"}
    supplied = body.get("password")
    if not isinstance(supplied, str):
        bottle.response.status = 400
        return {"success": False, "error": "password is required"}
    if not hmac.compare_digest(supplied, password):
        clear_ui_unlock_cookie()
        bottle.response.status = 401
        return {"success": False, "error": "incorrect password"}

    set_ui_unlock_cookie()
    return {
        "success": True,
        "enabled": True,
        "unlocked": True,
    }


@app.post("/ui-auth/lock")
def handle_ui_auth_lock():
    """Lock the UI for the current browser session."""
    clear_ui_unlock_cookie()
    return {
        "success": True,
        "enabled": ui_password_enabled(),
        "unlocked": False if ui_password_enabled() else True,
    }


@app.get("/api/stats")
def handle_api_stats():
    """Return the latest PID and telemetry snapshot."""
    log.info("/api/stats command received")
    if not monitor_authorized():
        return deny_http_unauthorized()
    oven = get_runtime().oven
    if hasattr(oven, "pid"):
        if hasattr(oven.pid, "pidstats"):
            stats = dict(oven.pid.pidstats)
            stats["telemetry"] = oven.get_state().get("telemetry", {})
            return json.dumps(stats)
    bottle.response.status = 503
    return {"success": False, "error": "pid stats unavailable"}


@app.post("/api")
def handle_api():
    """Handle HTTP kiln control and monitor commands."""
    log.info("/api is alive")
    parsed = _parse_api_body()
    if parsed is None or "success" in parsed:
        return parsed

    body = parsed
    cmd = body["cmd"]

    # Start a kiln schedule.
    if cmd == "run":
        if not control_authorized():
            audit_command("run", False, source="http", details={"profile": body.get("profile")})
            return deny_http_unauthorized()
        wanted = body.get("profile")
        if not isinstance(wanted, str) or not wanted.strip():
            bottle.response.status = 400
            return {"success": False, "error": "profile is required"}
        log.info("api requested run of profile = %s" % wanted)

        # Restarting or skipping ahead uses an explicit minute offset.
        startat = 0
        if "startat" in body:
            try:
                startat = max(0, int(body["startat"]))
            except (TypeError, ValueError):
                bottle.response.status = 400
                return {"success": False, "error": "startat must be an integer number of minutes"}
        runtime = get_runtime()
        oven = runtime.oven
        oven_watcher = runtime.oven_watcher

        # Explicit offsets disable seek-start behavior.
        allow_seek = True
        if startat > 0:
            allow_seek = False

        # Load the requested profile from disk.
        profile = find_profile(wanted)
        if profile is None:
            return {"success": False, "error": "profile %s not found" % wanted}

        # TODO: move JSON-to-Profile conversion into the Profile class.
        profile_json = json.dumps(profile)
        profile = Profile(profile_json)
        oven.run_profile(profile, startat=startat, allow_seek=allow_seek)
        oven_watcher.record(profile)
        audit_command("run", True, source="http", details={"profile": wanted, "startat": startat})

    elif cmd == "pause":
        if not control_authorized():
            audit_command("pause", False, source="http")
            return deny_http_unauthorized()
        oven = get_runtime().oven
        log.info("api pause command received")
        oven.state = "PAUSED"
        oven.emit_notification(
            "run_paused",
            {"profile": oven.profile.name if oven.profile else None, "run_id": oven.current_run_id},
        )
        audit_command("pause", True, source="http")

    elif cmd == "resume":
        if not control_authorized():
            audit_command("resume", False, source="http")
            return deny_http_unauthorized()
        oven = get_runtime().oven
        log.info("api resume command received")
        oven.state = "RUNNING"
        oven.emit_notification(
            "run_resumed",
            {"profile": oven.profile.name if oven.profile else None, "run_id": oven.current_run_id},
        )
        audit_command("resume", True, source="http")

    elif cmd == "stop":
        if not control_authorized():
            audit_command("stop", False, source="http")
            return deny_http_unauthorized()
        oven = get_runtime().oven
        log.info("api stop command received")
        oven.abort_run(reason="manual_stop_http")
        audit_command("stop", True, source="http")

    elif cmd == "memo":
        if not control_authorized():
            audit_command("memo", False, source="http")
            return deny_http_unauthorized()
        log.info("api memo command received")
        memo = body.get("memo")
        if not isinstance(memo, str):
            bottle.response.status = 400
            return {"success": False, "error": "memo must be a string"}
        log.info("memo=%s" % (memo))
        audit_command("memo", True, source="http", details={"memo": memo})

    # Return live PID statistics and telemetry.
    elif cmd == "stats":
        if not monitor_authorized():
            return deny_http_unauthorized()
        oven = get_runtime().oven
        log.info("api stats command received")
        if hasattr(oven, "pid"):
            if hasattr(oven.pid, "pidstats"):
                stats = dict(oven.pid.pidstats)
                stats["telemetry"] = oven.get_state().get("telemetry", {})
                return json.dumps(stats)
        bottle.response.status = 503
        return {"success": False, "error": "pid stats unavailable"}

    else:
        bottle.response.status = 400
        return {"success": False, "error": f"unknown cmd: {cmd}"}

    return {"success": True}


def find_profile(wanted):
    """Return a parsed profile object by name, or None when it is missing."""
    for profile in _load_profiles_from_disk():
        if profile["name"] == wanted:
            return profile
    return None


@app.route("/picoreflow/<filename:path>")
def send_static(filename):
    """Serve static assets from the bundled public directory."""
    log.debug("serving %s" % filename)
    return bottle.static_file(
        filename, root=os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "public")
    )


def get_websocket_from_request():
    """Return the websocket from the current request or abort on plain HTTP."""
    env = bottle.request.environ
    wsock = env.get("wsgi.websocket")
    if not wsock:
        bottle.abort(400, "Expected WebSocket request.")
    return wsock


@app.route("/control")
def handle_control():
    """Handle websocket control commands."""
    wsock = get_websocket_from_request()
    runtime = get_runtime()
    oven = runtime.oven
    oven_watcher = runtime.oven_watcher
    if not control_authorized():
        audit_command("ws_control_connect", False, source="websocket")
        deny_ws_unauthorized(wsock)
        log.warning("websocket (control) unauthorized")
        return
    audit_command("ws_control_connect", True, source="websocket")
    log.info("websocket (control) opened")
    while True:
        try:
            message = wsock.receive()
            if message:
                log.info("Received (control): %s" % message)
                try:
                    msgdict = json.loads(message)
                except json.JSONDecodeError:
                    wsock.send(json.dumps({"success": False, "error": "invalid json"}))
                    continue
                if msgdict.get("cmd") == "RUN":
                    log.info("RUN command received")
                    profile_obj = msgdict.get("profile")
                    if not isinstance(profile_obj, dict):
                        wsock.send(
                            json.dumps({"success": False, "error": "profile payload required"})
                        )
                        continue
                    profile_json = json.dumps(profile_obj)
                    profile = Profile(profile_json)
                    oven.run_profile(profile)
                    oven_watcher.record(profile)
                    audit_command(
                        "ws_run",
                        True,
                        source="websocket",
                        details={"profile": profile_obj.get("name") if profile_obj else None},
                    )
                elif msgdict.get("cmd") == "SIMULATE":
                    log.info("SIMULATE command received")
                    # Simulation websocket control is not implemented.
                elif msgdict.get("cmd") == "STOP":
                    log.info("Stop command received")
                    oven.abort_run(reason="manual_stop_ws")
                    audit_command("ws_stop", True, source="websocket")
            time.sleep(1)
        except WebSocketError as e:
            log.error(e)
            break
    log.info("websocket (control) closed")


@app.route("/storage")
def handle_storage():
    """Handle websocket profile storage requests."""
    wsock = get_websocket_from_request()
    if not monitor_authorized():
        audit_command("ws_storage_connect", False, source="websocket")
        deny_ws_unauthorized(wsock)
        log.warning("websocket (storage) unauthorized")
        return
    audit_command("ws_storage_connect", True, source="websocket")
    log.info("websocket (storage) opened")
    while True:
        try:
            message = wsock.receive()
            if not message:
                break
            log.debug("websocket (storage) received: %s" % message)

            try:
                msgdict = json.loads(message)
            except json.JSONDecodeError:
                msgdict = {}

            if message == "GET":
                log.info("GET command received")
                wsock.send(get_profiles())
                audit_command("ws_storage_get", True, source="websocket")
            elif msgdict.get("cmd") == "DELETE":
                if not control_authorized():
                    audit_command(
                        "ws_storage_delete",
                        False,
                        source="websocket",
                        details={"profile": msgdict.get("profile", {}).get("name")},
                    )
                    wsock.send(json.dumps({"success": False, "error": "unauthorized"}))
                    continue
                log.info("DELETE command received")
                profile_obj = msgdict.get("profile")
                ok, error = delete_profile(profile_obj)
                if ok:
                    msgdict["resp"] = "OK"
                else:
                    msgdict["resp"] = "FAIL"
                    msgdict["error"] = error
                wsock.send(json.dumps(msgdict))
                audit_command(
                    "ws_storage_delete",
                    ok,
                    source="websocket",
                    details={"profile": profile_obj.get("name") if profile_obj else None},
                )
                # wsock.send(get_profiles())
            elif msgdict.get("cmd") == "PUT":
                if not control_authorized():
                    audit_command(
                        "ws_storage_put",
                        False,
                        source="websocket",
                        details={"profile": msgdict.get("profile", {}).get("name")},
                    )
                    wsock.send(json.dumps({"success": False, "error": "unauthorized"}))
                    continue
                log.info("PUT command received")
                profile_obj = msgdict.get("profile")
                force = bool(msgdict.get("force", False))
                if profile_obj:
                    ok, error = save_profile(profile_obj, force)
                    if ok:
                        msgdict["resp"] = "OK"
                    else:
                        msgdict["resp"] = "FAIL"
                        msgdict["error"] = error or "save failed"
                    log.debug("websocket (storage) sent: %s" % message)

                    wsock.send(json.dumps(msgdict))
                    if ok:
                        wsock.send(get_profiles())
                    audit_command(
                        "ws_storage_put",
                        ok,
                        source="websocket",
                        details={
                            "profile": profile_obj.get("name") if profile_obj else None,
                            "result": msgdict.get("resp"),
                        },
                    )
            time.sleep(1)
        except WebSocketError:
            break
    log.info("websocket (storage) closed")


@app.route("/config")
def handle_config():
    """Return controller configuration over a websocket."""
    wsock = get_websocket_from_request()
    if not monitor_authorized():
        deny_ws_unauthorized(wsock)
        log.warning("websocket (config) unauthorized")
        return
    log.info("websocket (config) opened")
    while True:
        try:
            message = wsock.receive()
            wsock.send(get_config())
        except WebSocketError:
            break
        time.sleep(1)
    log.info("websocket (config) closed")


@app.route("/status")
def handle_status():
    """Stream live kiln status snapshots over a websocket."""
    wsock = get_websocket_from_request()
    if not monitor_authorized():
        deny_ws_unauthorized(wsock)
        log.warning("websocket (status) unauthorized")
        return
    runtime = get_runtime()
    runtime.oven_watcher.add_observer(wsock)
    log.info("websocket (status) opened")
    while True:
        try:
            message = wsock.receive()
            wsock.send("Your message was: %r" % message)
        except WebSocketError:
            break
        time.sleep(1)
    log.info("websocket (status) closed")


def get_profiles():
    """Serialize all stored profiles for websocket and HTTP responses."""
    return json.dumps(_load_profiles_from_disk())


def save_profile(profile, force=False):
    """Persist a profile payload to disk, optionally overwriting existing data."""
    if not isinstance(profile, dict):
        return False, "profile payload must be an object"
    filepath = _profile_file_path(profile.get("name"))
    if filepath is None:
        return False, "invalid profile name"
    profile = add_temp_units(profile)
    profile_json = json.dumps(profile)
    if not force and os.path.exists(filepath):
        log.error("Could not write, %s already exists" % filepath)
        return False, "Profile exists"
    os.makedirs(filepath.parent, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(profile_json)
    log.info("Wrote %s" % filepath)
    return True, None


def add_temp_units(profile):
    """Normalize stored profile temperatures to Celsius for portability."""
    if "temp_units" in profile:
        return profile
    profile["temp_units"] = "c"
    if config.temp_scale == "c":
        return profile
    if config.temp_scale == "f":
        profile = convert_to_c(profile)
        return profile


def convert_to_c(profile):
    """Convert profile data points from Fahrenheit to Celsius."""
    newdata = []
    for secs, temp in profile["data"]:
        temp = (5 / 9) * (temp - 32)
        newdata.append((secs, temp))
    profile["data"] = newdata
    return profile


def convert_to_f(profile):
    """Convert profile data points from Celsius to Fahrenheit."""
    newdata = []
    for secs, temp in profile["data"]:
        temp = ((9 / 5) * temp) + 32
        newdata.append((secs, temp))
    profile["data"] = newdata
    return profile


def normalize_temp_units(profiles):
    """Convert loaded profiles into the configured display temperature scale."""
    normalized = []
    for profile in profiles:
        if "temp_units" in profile:
            if config.temp_scale == "f" and profile["temp_units"] == "c":
                profile = convert_to_f(profile)
                profile["temp_units"] = "f"
        normalized.append(profile)
    return normalized


def delete_profile(profile):
    """Delete a stored profile after validating its payload and path."""
    if not isinstance(profile, dict):
        return False, "profile payload must be an object"
    filepath = _profile_file_path(profile.get("name"))
    if filepath is None:
        return False, "invalid profile name"
    if not filepath.exists():
        return False, "profile not found"
    os.remove(filepath)
    log.info("Deleted %s" % filepath)
    return True, None


def _jsonable_config_value(value):
    """Convert config values into JSON-safe scalars for UI inspection."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def get_config():
    """Return a JSON snapshot of UI-visible controller and hardware config."""
    return json.dumps(
        {
            "temp_scale": config.temp_scale,
            "time_scale_slope": config.time_scale_slope,
            "time_scale_profile": config.time_scale_profile,
            "kwh_rate": config.kwh_rate,
            "currency_type": config.currency_type,
            "hardware": {
                "simulate": bool(getattr(config, "simulate", False)),
                "relay": {
                    "gpio_heat": _jsonable_config_value(getattr(config, "gpio_heat", None)),
                    "gpio_heat_invert": bool(getattr(config, "gpio_heat_invert", False)),
                },
                "buzzer": {
                    "gpio_buzzer": _jsonable_config_value(getattr(config, "gpio_buzzer", None)),
                },
                "spi": {
                    "mode": "software"
                    if all(
                        hasattr(config, attr)
                        for attr in ("spi_sclk", "spi_mosi", "spi_miso", "spi_cs")
                    )
                    else "hardware",
                    "spi_sclk": _jsonable_config_value(getattr(config, "spi_sclk", None)),
                    "spi_mosi": _jsonable_config_value(getattr(config, "spi_mosi", None)),
                    "spi_miso": _jsonable_config_value(getattr(config, "spi_miso", None)),
                    "spi_cs": _jsonable_config_value(getattr(config, "spi_cs", None)),
                },
                "thermocouple": {
                    "board": "max31856"
                    if bool(getattr(config, "max31856", False))
                    else "max31855"
                    if bool(getattr(config, "max31855", False))
                    else "unknown",
                    "type": _jsonable_config_value(getattr(config, "thermocouple_type", None)),
                    "offset": getattr(config, "thermocouple_offset", 0),
                    "samples_per_cycle": getattr(config, "temperature_average_samples", None),
                    "sensor_time_wait": getattr(config, "sensor_time_wait", None),
                },
                "display": {
                    "enabled": bool(getattr(config, "display_enabled", False)),
                    "width": getattr(config, "display_width", None),
                    "height": getattr(config, "display_height", None),
                    "i2c_address": _jsonable_config_value(
                        hex(getattr(config, "display_i2c_address", 0))
                        if getattr(config, "display_i2c_address", None) is not None
                        else None
                    ),
                    "i2c_port": getattr(config, "display_i2c_port", None),
                },
                "power_sensor": {
                    "enabled": bool(getattr(config, "power_sensor_enabled", False)),
                    "type": _jsonable_config_value(getattr(config, "power_sensor_type", None)),
                    "port": _jsonable_config_value(getattr(config, "power_sensor_port", None)),
                    "baudrate": getattr(config, "power_sensor_baudrate", None),
                    "address": getattr(config, "power_sensor_address", None),
                    "poll_interval": getattr(config, "power_sensor_poll_interval", None),
                    "timeout": getattr(config, "power_sensor_timeout", None),
                    "stale_seconds": getattr(config, "power_sensor_stale_seconds", None),
                },
            },
        }
    )


def main():
    """Run the Bottle/Gevent controller server."""
    runtime = get_runtime()
    # Play the startup sound when available.
    if runtime.buzzer:
        try:
            runtime.buzzer.startup()
        except Exception as e:
            log.warning(f"Failed to play startup sound: {e}")

    ip = "0.0.0.0"
    port = config.listening_port
    log.info("listening on %s:%d" % (ip, port))

    try:
        server = WSGIServer((ip, port), app, handler_class=WebSocketHandler)
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down...")
        if runtime.buzzer:
            try:
                runtime.buzzer.cleanup()
            except Exception:
                pass
    except Exception as e:
        log.error(f"Fatal error: {e}")
        # Play the error sound on crash.
        if runtime.buzzer:
            try:
                runtime.buzzer.error()
            except Exception:
                pass
        raise


if __name__ == "__main__":
    main()
