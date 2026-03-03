#!/usr/bin/env python
"""Log kiln status websocket messages to CSV for offline analysis."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from typing import Any

import websocket

STD_HEADER = [
    "stamp",
    "runtime",
    "temperature",
    "target",
    "state",
    "heat",
    "totaltime",
    "profile",
]


PID_HEADER = [
    "pid_time",
    "pid_timeDelta",
    "pid_setpoint",
    "pid_ispoint",
    "pid_err",
    "pid_errDelta",
    "pid_p",
    "pid_i",
    "pid_d",
    "pid_kp",
    "pid_ki",
    "pid_kd",
    "pid_pid",
    "pid_out",
]


def logger(hostname: str, csvfile: str, noprofilestats: bool, pidstats: bool, stdout: bool) -> None:
    """Stream status updates and persist selected fields to CSV.

    CSV output makes long runs inspectable with common tooling while keeping
    runtime overhead low.
    """
    status_ws = websocket.WebSocket()
    out_dir = os.path.dirname(csvfile) or "."
    os.makedirs(out_dir, exist_ok=True)

    csv_fields = []
    if not noprofilestats:
        csv_fields += STD_HEADER
    if pidstats:
        csv_fields += PID_HEADER

    out = open(csvfile, "w")
    csv_out = csv.DictWriter(out, csv_fields, extrasaction="ignore")
    csv_out.writeheader()

    if stdout:
        csv_stdout = csv.DictWriter(sys.stdout, csv_fields, extrasaction="ignore", delimiter="\t")
        csv_stdout.writeheader()
    else:
        csv_stdout = None

    while True:
        try:
            msg: dict[str, Any] = json.loads(status_ws.recv())

        except websocket.WebSocketException:
            try:
                status_ws.connect(f"ws://{hostname}/status")
            except Exception:
                time.sleep(5)

            continue

        if msg.get("type") == "backlog":
            continue

        if not noprofilestats:
            msg["stamp"] = time.time()
        if pidstats and "pidstats" in msg:
            for k, v in msg.get("pidstats", {}).items():
                msg[f"pid_{k}"] = v

        csv_out.writerow(msg)
        out.flush()

        if stdout:
            for k in list(msg.keys()):
                v = msg[k]
                if isinstance(v, float):
                    msg[k] = f"{v:5.3f}"
            csv_stdout.writerow(msg)
            sys.stdout.flush()


if __name__ == "__main__":
    default_csvfile = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "storage", "logs", "kiln-stats.csv")
    )
    parser = argparse.ArgumentParser(description="Log kiln data for analysis.")
    parser.add_argument(
        "--hostname", type=str, default="localhost:8081", help="The kiln-controller hostname:port"
    )
    parser.add_argument(
        "--csvfile", type=str, default=default_csvfile, help="Where to write the kiln stats to"
    )
    parser.add_argument("--pidstats", action="store_true", help="Include PID stats")
    parser.add_argument(
        "--noprofilestats",
        action="store_true",
        help="Do not store profile stats (default is to store them)",
    )
    parser.add_argument("--stdout", action="store_true", help="Also print to stdout")
    args = parser.parse_args()

    logger(args.hostname, args.csvfile, args.noprofilestats, args.pidstats, args.stdout)
