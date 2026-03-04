import json
import logging
import queue
import threading
import urllib.parse
import urllib.request

import config

log = logging.getLogger(__name__)


class NotificationManager:
    """Background notification sender with optional ntfy backend."""

    def __init__(self):
        self.enabled = bool(getattr(config, "notifications_enabled", False))
        self.provider = getattr(config, "notification_provider", "ntfy")
        self.timeout = float(getattr(config, "notifications_timeout_seconds", 4.0))
        self.max_queue = int(getattr(config, "notifications_queue_size", 200))
        self.queue = queue.Queue(maxsize=self.max_queue)
        self.worker = None
        self._stop = threading.Event()

        # ntfy-specific options
        self.ntfy_server = str(getattr(config, "ntfy_server", "https://ntfy.sh")).rstrip("/")
        self.ntfy_topic = getattr(config, "ntfy_topic", None)
        self.ntfy_token = getattr(config, "ntfy_access_token", None)
        self.ntfy_default_priority = str(getattr(config, "ntfy_default_priority", "default"))
        self.ntfy_default_tags = list(getattr(config, "ntfy_default_tags", ["kiln"]))

    def start(self):
        if not self.enabled:
            log.info("notifications disabled")
            return
        if self.provider != "ntfy":
            log.warning("unknown notification provider '%s'; notifications disabled", self.provider)
            return
        if not self.ntfy_topic:
            log.warning(
                "notifications enabled but ntfy_topic is not configured; notifications disabled"
            )
            return
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._run, name="notification-worker", daemon=True)
        self.worker.start()
        log.info("notification worker started (provider=%s)", self.provider)

    def stop(self):
        self._stop.set()

    def emit_event(self, event, payload=None):
        if not self.enabled:
            return
        payload = payload or {}
        title, message, priority, tags = self._format_event(event, payload)
        if not message:
            return
        job = {
            "title": title,
            "message": message,
            "priority": priority or self.ntfy_default_priority,
            "tags": tags or self.ntfy_default_tags,
            "event": event,
            "payload": payload,
        }
        try:
            self.queue.put_nowait(job)
        except queue.Full:
            log.warning("notification queue full; dropping event=%s", event)

    def _run(self):
        while not self._stop.is_set():
            try:
                job = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._send(job)
            except Exception as exc:
                log.error("notification send failed: %s", exc)
            finally:
                self.queue.task_done()

    def _send(self, job):
        if self.provider == "ntfy":
            self._send_ntfy(job)

    def _send_ntfy(self, job):
        topic = urllib.parse.quote(str(self.ntfy_topic), safe="")
        url = f"{self.ntfy_server}/{topic}"

        body = job["message"].encode("utf-8")
        headers = {
            "Title": job["title"][:120] if job["title"] else "Kiln Alert",
            "Priority": str(job.get("priority", "default")),
            "Tags": ",".join(job.get("tags", [])),
            "Content-Type": "text/plain; charset=utf-8",
        }
        if self.ntfy_token:
            headers["Authorization"] = f"Bearer {self.ntfy_token}"

        req = urllib.request.Request(url=url, data=body, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"ntfy responded with status {resp.status}")
        log.info("notification sent: %s", job.get("event"))

    def _format_event(self, event, payload):
        profile = payload.get("profile") or "unknown profile"
        reason = payload.get("reason")
        temp_scale = str(getattr(config, "temp_scale", "f")).upper()

        if event == "run_started":
            startat = int(payload.get("startat_minutes", 0))
            if startat > 0:
                return (
                    "Kiln Run Started",
                    f"Profile '{profile}' started at +{startat:d} min.",
                    "default",
                    ["kiln", "start"],
                )
            return (
                "Kiln Run Started",
                f"Profile '{profile}' started.",
                "default",
                ["kiln", "start"],
            )

        if event == "run_paused":
            return (
                "Kiln Run Paused",
                f"Profile '{profile}' paused.",
                "high",
                ["kiln", "pause"],
            )

        if event == "run_resumed":
            return (
                "Kiln Run Resumed",
                f"Profile '{profile}' resumed.",
                "default",
                ["kiln", "resume"],
            )

        if event == "run_finished":
            runtime_hours = float(payload.get("runtime_hours", 0.0))
            if reason == "schedule_complete":
                return (
                    "Kiln Run Complete",
                    f"Profile '{profile}' completed in {runtime_hours:.2f} h.",
                    "default",
                    ["kiln", "complete"],
                )
            if reason and str(reason).startswith("emergency_"):
                return (
                    "Kiln Emergency Stop",
                    f"Profile '{profile}' stopped ({reason}).",
                    "urgent",
                    ["kiln", "emergency", "alert"],
                )
            return (
                "Kiln Run Stopped",
                "Profile '{}' stopped ({}).".format(profile, reason or "unknown"),
                "high",
                ["kiln", "stop"],
            )

        if event == "sensor_fault":
            error_rate = float(payload.get("error_rate_pct", 0.0))
            return (
                "Kiln Sensor Fault",
                f"Thermocouple error rate {error_rate:.1f}%.",
                "urgent",
                ["kiln", "sensor", "alert"],
            )

        if event == "issue_detected":
            issue = str(payload.get("issue", "unknown_issue"))
            if issue == "temperature_too_high":
                temperature = float(payload.get("temperature", 0.0))
                limit = float(payload.get("limit", 0.0))
                return (
                    "Kiln Over-Temp Warning",
                    f"Temp {temperature:.1f}{temp_scale} is at/over limit {limit:.1f}{temp_scale}.",
                    "urgent",
                    ["kiln", "issue", "alert"],
                )
            if issue == "thermocouple_error_rate_high":
                rate = float(payload.get("error_rate_pct", 0.0))
                return (
                    "Kiln Sensor Warning",
                    f"Thermocouple error rate high ({rate:.1f}%).",
                    "high",
                    ["kiln", "issue", "sensor"],
                )
            if issue == "heater_commanded_no_current":
                current_amps = payload.get("current_amps")
                threshold = float(payload.get("threshold_amps", 0.0))
                window = float(payload.get("window_seconds", 0.0))
                if current_amps is None:
                    return (
                        "Kiln Power Warning",
                        f"Heater was commanded but current remained below threshold for {window:.0f}s.",
                        "high",
                        ["kiln", "issue", "power"],
                    )
                return (
                    "Kiln Power Warning",
                    (
                        f"Heater commanded but current stayed low "
                        f"({float(current_amps):.2f}A <= {threshold:.2f}A for {window:.0f}s)."
                    ),
                    "high",
                    ["kiln", "issue", "power"],
                )
            if issue == "power_sensor_stale":
                stale = float(payload.get("stale_seconds", 0.0))
                return (
                    "Kiln Power Sensor Stale",
                    f"Power sensor has not updated for {stale:.0f}s.",
                    "high",
                    ["kiln", "issue", "sensor"],
                )
            if issue == "catchup_shadow_would_extend":
                avg_error = float(payload.get("avg_error_confidence", 0.0))
                rise = float(payload.get("rise_rate_trend_deg_per_hour", 0.0))
                return (
                    "Kiln Catch-Up Shadow",
                    (
                        "Shadow mode: sustained lag detected but trend still rising "
                        f"(avg lag {avg_error:.1f}{temp_scale}, rise {rise:.1f}{temp_scale}/h)."
                    ),
                    "default",
                    ["kiln", "issue", "shadow"],
                )
            if issue == "catchup_shadow_would_abort":
                avg_error = float(payload.get("avg_error_confidence", 0.0))
                lagging = float(payload.get("lagging_seconds", 0.0))
                return (
                    "Kiln Catch-Up Shadow",
                    (
                        "Shadow mode: run would be aborted for sustained inability to catch up "
                        f"(avg lag {avg_error:.1f}{temp_scale}, lag duration {lagging/60.0:.0f}m)."
                    ),
                    "high",
                    ["kiln", "issue", "shadow", "alert"],
                )
            return (
                "Kiln Issue",
                f"Issue detected: {issue}",
                "high",
                ["kiln", "issue"],
            )

        if event == "abnormal_deviation":
            temperature = float(payload.get("temperature", 0.0))
            target = float(payload.get("target", 0.0))
            drop = float(payload.get("temperature_drop", 0.0))
            window = float(payload.get("drop_window_seconds", 0.0))
            return (
                "Kiln Abnormal Deviation",
                (
                    f"Temp dropped {abs(drop):.1f}{temp_scale} in {window:.0f}s "
                    f"({temperature:.1f}{temp_scale} vs {target:.1f}{temp_scale} target)."
                ),
                "high",
                ["kiln", "deviation", "alert"],
            )

        if event == "profile_rate_change":
            old_rate = float(payload.get("previous_rate_deg_per_hour", 0.0))
            new_rate = float(payload.get("new_rate_deg_per_hour", 0.0))
            checkpoint_hours = float(payload.get("checkpoint_hours", 0.0))
            target_temp = float(payload.get("temperature_target", 0.0))
            return (
                "Kiln Profile Segment Change",
                (
                    f"At {checkpoint_hours:.2f}h target {target_temp:.0f}{temp_scale}, "
                    f"rate {old_rate:.0f} -> {new_rate:.0f} {temp_scale}/h."
                ),
                "default",
                ["kiln", "profile", "checkpoint"],
            )

        if event == "temp_milestone_reached":
            milestone = float(payload.get("milestone_temp", 0.0))
            runtime_hours = float(payload.get("runtime_hours", 0.0))
            return (
                "Kiln Temperature Milestone",
                f"Reached {milestone:.0f}{temp_scale} at {runtime_hours:.2f}h runtime.",
                "default",
                ["kiln", "milestone", "temperature"],
            )

        # Fallback for ad-hoc notifications.
        return (
            "Kiln Event",
            json.dumps({"event": event, "payload": payload}),
            "default",
            ["kiln"],
        )
