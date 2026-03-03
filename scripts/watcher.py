#!/usr/bin/env python
"""Watch kiln stats endpoint and alert on persistent anomalies."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

# this monitors your kiln stats every N seconds
# if X checks fail, an alert is sent to a slack channel
# configure an incoming web hook on the slack channel
# set slack_hook_url to that

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class Watcher:
    """Poll kiln stats and emit alerts when health checks repeatedly fail."""

    def __init__(
        self,
        kiln_url: str,
        slack_hook_url: str,
        bad_check_limit: int = 6,
        temp_error_limit: float = 10,
        sleepfor: int = 10,
    ) -> None:
        self.kiln_url = kiln_url
        self.slack_hook_url = slack_hook_url
        self.bad_check_limit = bad_check_limit
        self.temp_error_limit = temp_error_limit
        self.sleepfor = sleepfor
        self.bad_checks = 0
        self.stats: dict[str, Any] = {}

    def get_stats(self) -> dict[str, Any]:
        """Read current kiln stats, returning an empty dict on transient failures."""
        try:
            r = requests.get(self.kiln_url, timeout=1)
            return r.json()
        except requests.exceptions.Timeout:
            log.error("network timeout. check kiln_url and port.")
            return {}
        except requests.exceptions.ConnectionError:
            log.error("network connection error. check kiln_url and port.")
            return {}
        except Exception:
            return {}

    def send_alert(self, msg: str) -> None:
        """Send a message to the configured Slack webhook endpoint."""
        log.error("sending alert: %s" % msg)
        try:
            requests.post(self.slack_hook_url, json={"text": msg})
        except Exception:
            pass

    def has_errors(self) -> bool:
        """Return whether latest stats indicate a fault condition."""
        if "time" not in self.stats:
            log.error("no data")
            return True
        if "err" in self.stats:
            if abs(self.stats["err"]) > self.temp_error_limit:
                log.error("temp out of whack %0.2f" % self.stats["err"])
                return True
        return False

    def run(self) -> None:
        """Run polling loop forever, alerting on repeated bad checks."""
        log.info("started watching %s" % self.kiln_url)
        while True:
            self.stats = self.get_stats()
            if self.has_errors():
                self.bad_checks = self.bad_checks + 1
            else:
                try:
                    log.info(
                        "OK temp=%0.2f target=%0.2f error=%0.2f"
                        % (self.stats["ispoint"], self.stats["setpoint"], self.stats["err"])
                    )
                except Exception:
                    pass

            if self.bad_checks >= self.bad_check_limit:
                msg = "error kiln needs help. %s" % json.dumps(self.stats, indent=2, sort_keys=True)
                self.send_alert(msg)
                self.bad_checks = 0

            time.sleep(self.sleepfor)


if __name__ == "__main__":
    Watcher(
        kiln_url="http://192.168.1.84:8081/api/stats",
        slack_hook_url="you must add this",
        bad_check_limit=6,
        temp_error_limit=10,
        sleepfor=10,
    ).run()
