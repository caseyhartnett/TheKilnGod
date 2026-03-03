#!/usr/bin/env python
"""HTTP and WebSocket API layer for kiln control and monitoring."""

import json
import logging
import os
import sys
import time

import bottle

# try/except removed here on purpose so folks can see why things break
import config

# from bottle import post, get
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

from .buzzer import Buzzer
from .display_updater import DisplayUpdater
from .homeassistant_mqtt import HomeAssistantMQTT
from .notifications import NotificationManager
from .oven import Profile, RealOven, SimulatedOven
from .oven_watcher import OvenWatcher

app = bottle.Bottle()

# Initialize buzzer (only for real oven)
buzzer = None
if not config.simulate:
    try:
        buzzer = Buzzer()
    except Exception as e:
        log.warning(f"Failed to initialize buzzer: {e}")


def get_request_token():
    token = bottle.request.get_header("X-API-Token")
    if not token:
        token = bottle.request.query.get("token")
    return token


def get_token_role(token):
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
    monitor_token = getattr(config, "api_monitor_token", None)
    control_token = getattr(config, "api_control_token", None)
    got = get_request_token()

    if control_token:
        return got == control_token
    if monitor_token:
        return got == monitor_token
    return True


def monitor_authorized():
    monitor_token = getattr(config, "api_monitor_token", None)
    control_token = getattr(config, "api_control_token", None)
    got = get_request_token()

    if monitor_token:
        return got == monitor_token or (control_token and got == control_token)
    if control_token:
        return got == control_token
    return True


def deny_http_unauthorized():
    bottle.response.status = 401
    return {"success": False, "error": "unauthorized"}


def deny_ws_unauthorized(wsock):
    try:
        wsock.send(json.dumps({"success": False, "error": "unauthorized"}))
    except Exception:
        pass
    try:
        wsock.close()
    except Exception:
        pass


def load_run_health_exclusions():
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


if config.simulate == True:
    log.info("this is a simulation")
    oven = SimulatedOven()
else:
    log.info("this is a real kiln")
    oven = RealOven(buzzer=buzzer)

notifier = NotificationManager()
notifier.start()
oven.set_notifier(notifier)
ovenWatcher = OvenWatcher(oven)
# this ovenwatcher is used in the oven class for restarts
oven.set_ovenwatcher(ovenWatcher)

# Initialize and start display updater
if getattr(config, "display_enabled", True):
    display_updater = DisplayUpdater(oven, update_interval=2.0)
    display_updater.start()
    log.info("Display updater started")
else:
    log.info("Display disabled in config")

# Initialize and start Home Assistant MQTT updater
if getattr(config, "ha_mqtt_enabled", False):
    ha_mqtt = HomeAssistantMQTT(oven)
    ha_mqtt.start()
    log.info("Home Assistant MQTT updater started")
else:
    log.info("Home Assistant MQTT disabled in config")


@app.route("/")
def index():
    return bottle.redirect("/picoreflow/index.html")


@app.route("/state")
def state():
    return bottle.redirect("/picoreflow/state.html")


@app.route("/v2")
def v2():
    return bottle.redirect("/picoreflow/v2/index.html")


@app.get("/api/stats")
def handle_api():
    log.info("/api/stats command received")
    if not monitor_authorized():
        return deny_http_unauthorized()
    if hasattr(oven, "pid"):
        if hasattr(oven.pid, "pidstats"):
            stats = dict(oven.pid.pidstats)
            stats["telemetry"] = oven.get_state().get("telemetry", {})
            return json.dumps(stats)


@app.post("/api")
def handle_api():
    log.info("/api is alive")

    # run a kiln schedule
    if bottle.request.json["cmd"] == "run":
        if not control_authorized():
            audit_command(
                "run", False, source="http", details={"profile": bottle.request.json.get("profile")}
            )
            return deny_http_unauthorized()
        wanted = bottle.request.json["profile"]
        log.info("api requested run of profile = %s" % wanted)

        # start at a specific minute in the schedule
        # for restarting and skipping over early parts of a schedule
        startat = 0
        if "startat" in bottle.request.json:
            startat = bottle.request.json["startat"]

        # Shut off seek if start time has been set
        allow_seek = True
        if startat > 0:
            allow_seek = False

        # get the wanted profile/kiln schedule
        profile = find_profile(wanted)
        if profile is None:
            return {"success": False, "error": "profile %s not found" % wanted}

        # FIXME juggling of json should happen in the Profile class
        profile_json = json.dumps(profile)
        profile = Profile(profile_json)
        oven.run_profile(profile, startat=startat, allow_seek=allow_seek)
        ovenWatcher.record(profile)
        audit_command("run", True, source="http", details={"profile": wanted, "startat": startat})

    if bottle.request.json["cmd"] == "pause":
        if not control_authorized():
            audit_command("pause", False, source="http")
            return deny_http_unauthorized()
        log.info("api pause command received")
        oven.state = "PAUSED"
        oven.emit_notification(
            "run_paused",
            {"profile": oven.profile.name if oven.profile else None, "run_id": oven.current_run_id},
        )
        audit_command("pause", True, source="http")

    if bottle.request.json["cmd"] == "resume":
        if not control_authorized():
            audit_command("resume", False, source="http")
            return deny_http_unauthorized()
        log.info("api resume command received")
        oven.state = "RUNNING"
        oven.emit_notification(
            "run_resumed",
            {"profile": oven.profile.name if oven.profile else None, "run_id": oven.current_run_id},
        )
        audit_command("resume", True, source="http")

    if bottle.request.json["cmd"] == "stop":
        if not control_authorized():
            audit_command("stop", False, source="http")
            return deny_http_unauthorized()
        log.info("api stop command received")
        oven.abort_run(reason="manual_stop_http")
        audit_command("stop", True, source="http")

    if bottle.request.json["cmd"] == "memo":
        if not control_authorized():
            audit_command("memo", False, source="http")
            return deny_http_unauthorized()
        log.info("api memo command received")
        memo = bottle.request.json["memo"]
        log.info("memo=%s" % (memo))
        audit_command("memo", True, source="http", details={"memo": memo})

    # get stats during a run
    if bottle.request.json["cmd"] == "stats":
        if not monitor_authorized():
            return deny_http_unauthorized()
        log.info("api stats command received")
        if hasattr(oven, "pid"):
            if hasattr(oven.pid, "pidstats"):
                stats = dict(oven.pid.pidstats)
                stats["telemetry"] = oven.get_state().get("telemetry", {})
                return json.dumps(stats)

    return {"success": True}


def find_profile(wanted):
    """
    given a wanted profile name, find it and return the parsed
    json profile object or None.
    """
    # load all profiles from disk
    profiles = get_profiles()
    json_profiles = json.loads(profiles)

    # find the wanted profile
    for profile in json_profiles:
        if profile["name"] == wanted:
            return profile
    return None


@app.route("/picoreflow/:filename#.*#")
def send_static(filename):
    log.debug("serving %s" % filename)
    return bottle.static_file(
        filename, root=os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "public")
    )


def get_websocket_from_request():
    env = bottle.request.environ
    wsock = env.get("wsgi.websocket")
    if not wsock:
        abort(400, "Expected WebSocket request.")
    return wsock


@app.route("/control")
def handle_control():
    wsock = get_websocket_from_request()
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
                msgdict = json.loads(message)
                if msgdict.get("cmd") == "RUN":
                    log.info("RUN command received")
                    profile_obj = msgdict.get("profile")
                    if profile_obj:
                        profile_json = json.dumps(profile_obj)
                        profile = Profile(profile_json)
                    oven.run_profile(profile)
                    ovenWatcher.record(profile)
                    audit_command(
                        "ws_run",
                        True,
                        source="websocket",
                        details={"profile": profile_obj.get("name") if profile_obj else None},
                    )
                elif msgdict.get("cmd") == "SIMULATE":
                    log.info("SIMULATE command received")
                    # profile_obj = msgdict.get('profile')
                    # if profile_obj:
                    #    profile_json = json.dumps(profile_obj)
                    #    profile = Profile(profile_json)
                    # simulated_oven = Oven(simulate=True, time_step=0.05)
                    # simulation_watcher = OvenWatcher(simulated_oven)
                    # simulation_watcher.add_observer(wsock)
                    # simulated_oven.run_profile(profile)
                    # simulation_watcher.record(profile)
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
            except:
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
                if delete_profile(profile_obj):
                    msgdict["resp"] = "OK"
                wsock.send(json.dumps(msgdict))
                audit_command(
                    "ws_storage_delete",
                    True,
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
                # force = msgdict.get('force', False)
                force = True
                if profile_obj:
                    # del msgdict["cmd"]
                    if save_profile(profile_obj, force):
                        msgdict["resp"] = "OK"
                    else:
                        msgdict["resp"] = "FAIL"
                    log.debug("websocket (storage) sent: %s" % message)

                    wsock.send(json.dumps(msgdict))
                    wsock.send(get_profiles())
                    audit_command(
                        "ws_storage_put",
                        True,
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
    wsock = get_websocket_from_request()
    if not monitor_authorized():
        deny_ws_unauthorized(wsock)
        log.warning("websocket (status) unauthorized")
        return
    ovenWatcher.add_observer(wsock)
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
    try:
        profile_files = os.listdir(profile_path)
    except:
        profile_files = []
    profiles = []
    for filename in profile_files:
        with open(os.path.join(profile_path, filename)) as f:
            profiles.append(json.load(f))
    profiles = normalize_temp_units(profiles)
    return json.dumps(profiles)


def save_profile(profile, force=False):
    profile = add_temp_units(profile)
    profile_json = json.dumps(profile)
    filename = profile["name"] + ".json"
    filepath = os.path.join(profile_path, filename)
    if not force and os.path.exists(filepath):
        log.error("Could not write, %s already exists" % filepath)
        return False
    with open(filepath, "w+") as f:
        f.write(profile_json)
        f.close()
    log.info("Wrote %s" % filepath)
    return True


def add_temp_units(profile):
    """
    always store the temperature in degrees c
    this way folks can share profiles
    """
    if "temp_units" in profile:
        return profile
    profile["temp_units"] = "c"
    if config.temp_scale == "c":
        return profile
    if config.temp_scale == "f":
        profile = convert_to_c(profile)
        return profile


def convert_to_c(profile):
    newdata = []
    for secs, temp in profile["data"]:
        temp = (5 / 9) * (temp - 32)
        newdata.append((secs, temp))
    profile["data"] = newdata
    return profile


def convert_to_f(profile):
    newdata = []
    for secs, temp in profile["data"]:
        temp = ((9 / 5) * temp) + 32
        newdata.append((secs, temp))
    profile["data"] = newdata
    return profile


def normalize_temp_units(profiles):
    normalized = []
    for profile in profiles:
        if "temp_units" in profile:
            if config.temp_scale == "f" and profile["temp_units"] == "c":
                profile = convert_to_f(profile)
                profile["temp_units"] = "f"
        normalized.append(profile)
    return normalized


def delete_profile(profile):
    profile_json = json.dumps(profile)
    filename = profile["name"] + ".json"
    filepath = os.path.join(profile_path, filename)
    os.remove(filepath)
    log.info("Deleted %s" % filepath)
    return True


def get_config():
    return json.dumps(
        {
            "temp_scale": config.temp_scale,
            "time_scale_slope": config.time_scale_slope,
            "time_scale_profile": config.time_scale_profile,
            "kwh_rate": config.kwh_rate,
            "currency_type": config.currency_type,
        }
    )


def main():
    # Play startup sound
    if buzzer:
        try:
            buzzer.startup()
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
        if buzzer:
            try:
                buzzer.cleanup()
            except:
                pass
    except Exception as e:
        log.error(f"Fatal error: {e}")
        # Play error sound on crash
        if buzzer:
            try:
                buzzer.error()
            except:
                pass
        raise


if __name__ == "__main__":
    main()
