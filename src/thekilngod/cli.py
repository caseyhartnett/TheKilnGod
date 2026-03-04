#!/usr/bin/env python3
"""Unified CLI for TheKilnGod."""

from __future__ import annotations

import argparse
import runpy
import sys
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_script(relative_path: str, args: list[str]) -> int:
    """Execute a repository script while preserving caller argv semantics.

    Delegation via `runpy` keeps existing script behavior intact, which avoids
    regressions while consolidating the command surface.
    """
    script_path = REPO_ROOT / relative_path
    old_argv = sys.argv[:]
    try:
        sys.argv = [str(script_path), *args]
        runpy.run_path(str(script_path), run_name="__main__")
        return 0
    finally:
        sys.argv = old_argv


def _run_callable(fn: Callable[[], int | None], argv0: str, args: list[str]) -> int:
    """Invoke a callable entrypoint with temporary argv override.

    Some existing modules parse `sys.argv` directly; this adapter preserves
    those expectations without duplicating argument parsing logic.
    """
    old_argv = sys.argv[:]
    try:
        sys.argv = [argv0, *args]
        result = fn()
        return int(result or 0)
    finally:
        sys.argv = old_argv


def _doctor() -> int:
    """Print quick environment checks used for local triage."""
    checks = []
    checks.append(("python", sys.version.split()[0]))
    checks.append(("repo", str(REPO_ROOT)))
    checks.append(("config.py", "ok" if (REPO_ROOT / "config.py").exists() else "missing"))
    checks.append(
        ("profiles", "ok" if (REPO_ROOT / "storage" / "profiles").exists() else "missing")
    )
    checks.append(("public", "ok" if (REPO_ROOT / "public").exists() else "missing"))
    checks.append(("ui-v2", "ok" if (REPO_ROOT / "ui-v2").exists() else "missing"))

    for name, status in checks:
        print(f"{name:12} {status}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser and subcommand tree."""
    parser = argparse.ArgumentParser(
        prog="thekilngod",
        description="Unified TheKilnGod command line",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("server", help="Run kiln controller server")

    sub.add_parser("run-health", help="Run health trends utility")

    sub.add_parser("tuner", help="Run kiln tuning utility")

    sub.add_parser("logger", help="Run websocket logger")

    sub.add_parser("firing-analyzer", help="Estimate cone from profile plan and/or run logs")

    sub.add_parser("gpio-readall", help="Show GPIO state table")

    sub.add_parser("watcher", help="Run external watcher utility")

    test = sub.add_parser("test", help="Run hardware test scripts")
    test_sub = test.add_subparsers(dest="test_command", required=True)

    for name in [
        "thermocouple",
        "output",
        "power",
        "buzzer",
        "display",
        "image-display",
        "mqtt",
        "upspack",
        "upspack-9600",
    ]:
        test_sub.add_parser(name)

    sub.add_parser("doctor", help="Check local runtime prerequisites")

    return parser


def main() -> int:
    """Route CLI invocations to stable runtime or utility entrypoints."""
    parser = build_parser()
    ns, remainder = parser.parse_known_args()

    if ns.command == "server":
        from .controller import main as controller_main

        return controller_main() or 0
    if ns.command == "run-health":
        from .run_health_trends import main as run_health_main

        return _run_callable(run_health_main, "run-health", remainder)
    if ns.command == "tuner":
        return _run_script("scripts/kiln_tuner.py", remainder)
    if ns.command == "logger":
        return _run_script("scripts/kiln_logger.py", remainder)
    if ns.command == "firing-analyzer":
        from .firing_analyzer import main as firing_analyzer_main

        return _run_callable(firing_analyzer_main, "firing-analyzer", remainder)
    if ns.command == "gpio-readall":
        return _run_script("scripts/gpio_readall.py", remainder)
    if ns.command == "watcher":
        return _run_script("scripts/watcher.py", remainder)
    if ns.command == "doctor":
        return _doctor()

    if ns.command == "test":
        mapping = {
            "thermocouple": "scripts/test_thermocouple.py",
            "output": "scripts/test_output.py",
            "power": "scripts/test_power_sensor.py",
            "buzzer": "tests/hardware/test_buzzer.py",
            "display": "tests/hardware/test_display.py",
            "image-display": "tests/hardware/test_image_display.py",
            "mqtt": "tests/hardware/test_mqtt_simple.py",
            "upspack": "tests/hardware/test_upspack.py",
            "upspack-9600": "tests/hardware/test_upspack_9600.py",
        }
        return _run_script(mapping[ns.test_command], remainder)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
