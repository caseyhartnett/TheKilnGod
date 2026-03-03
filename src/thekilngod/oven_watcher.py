"""WebSocket observer fan-out for kiln state updates.

This module keeps a short in-memory backlog for newly connected clients.
It intentionally does not persist run state to disk; runtime safety behavior
remains owned by the `Oven` controller logic.
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
import time
from collections.abc import Mapping
from typing import Any, Protocol

log = logging.getLogger(__name__)


class SupportsSend(Protocol):
    """Minimal websocket-like send interface used by the watcher."""

    def send(self, payload: str) -> None:
        """Send a serialized payload to a connected client."""


class OvenWatcher(threading.Thread):
    """Broadcast oven state snapshots to subscribed websocket clients."""

    def __init__(self, oven: Any) -> None:
        super().__init__(daemon=True)
        self.last_profile: Any | None = None
        self.last_log: list[dict[str, Any]] = []
        self.started: datetime.datetime | None = None
        self.recording = False
        self.observers: list[SupportsSend] = []
        self.oven = oven
        self.start()

    def run(self) -> None:
        """Continuously publish oven state to all observers."""
        while True:
            oven_state = self.oven.get_state()

            if oven_state.get("state") == "RUNNING":
                self.last_log.append(oven_state)
            else:
                self.recording = False

            self.notify_all(oven_state)
            time.sleep(self.oven.time_step)

    def lastlog_subset(self, maxpts: int = 50) -> list[dict[str, Any]]:
        """Down-sample backlog so initial websocket replay stays bounded."""
        totalpts = len(self.last_log)
        if totalpts <= maxpts:
            return self.last_log
        every_nth = int(totalpts / (maxpts - 1))
        return self.last_log[::every_nth]

    def record(self, profile: Any) -> None:
        """Start a new backlog series for the active run profile."""
        self.last_profile = profile
        self.last_log = []
        self.started = datetime.datetime.now()
        self.recording = True
        self.last_log.append(self.oven.get_state())

    def add_observer(self, observer: SupportsSend) -> None:
        """Attach a websocket client and immediately send backlog context."""
        profile_payload: dict[str, Any] | None
        if self.last_profile:
            profile_payload = {
                "name": self.last_profile.name,
                "data": self.last_profile.data,
                "type": "profile",
            }
        else:
            profile_payload = None

        backlog = {
            "type": "backlog",
            "profile": profile_payload,
            "log": self.lastlog_subset(),
        }
        backlog_json = json.dumps(backlog)

        try:
            observer.send(backlog_json)
        except Exception:
            log.error("Could not send backlog to new observer")

        self.observers.append(observer)

    def notify_all(self, message: Mapping[str, Any] | dict[str, Any]) -> None:
        """Broadcast a state payload and evict disconnected observers."""
        message_json = json.dumps(message)
        log.debug("sending to %d clients: %s", len(self.observers), message_json)

        alive_observers: list[SupportsSend] = []
        for wsock in self.observers:
            try:
                wsock.send(message_json)
                alive_observers.append(wsock)
            except Exception:
                log.error("could not write to socket %s", wsock)

        self.observers = alive_observers
