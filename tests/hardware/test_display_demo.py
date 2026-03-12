"""Integrated OLED demo and preview export for the kiln display flow."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pytest

from thekilngod.display import FIRING_FLAME_FRAME_NAMES, STARTUP_FRAME_NAMES, KilnDisplay
from thekilngod.oven import describe_run_reason

pytestmark = pytest.mark.hardware


class DemoPlayer:
    """Play frames to hardware, preview exports, or both."""

    def __init__(self, display: KilnDisplay, preview_dir: str | None = None) -> None:
        self.display = display
        self.preview_dir = Path(preview_dir).expanduser() if preview_dir else None
        self.frames: list[tuple[str, object, float]] = []

    def show(self, name: str, image, seconds: float) -> None:
        if self.display.initialized:
            self.display.display_image(image)
            time.sleep(seconds)
        if self.preview_dir:
            self.frames.append((name, image.copy(), seconds))

    def export(self) -> None:
        if not self.preview_dir or not self.frames:
            return
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        durations = []
        images = []
        for index, (name, image, seconds) in enumerate(self.frames):
            filename = f"{index:03d}-{name}.png"
            image.save(self.preview_dir / filename)
            durations.append(max(40, int(seconds * 1000)))
            images.append(image)
        images[0].save(
            self.preview_dir / "display-demo.gif",
            save_all=True,
            append_images=images[1:],
            duration=durations,
            loop=0,
        )


def running_state(profile: str, temperature: float, target: float, runtime: float, heat: float) -> dict[str, object]:
    """Return one fake running state shaped like the real runtime payload."""
    return {
        "state": "RUNNING",
        "profile": profile,
        "temperature": temperature,
        "target": target,
        "runtime": runtime,
        "totaltime": 8.5 * 3600,
        "heat": heat,
    }


def paused_state(profile: str, temperature: float, target: float, runtime: float) -> dict[str, object]:
    """Return one fake paused state shaped like the real runtime payload."""
    return {
        "state": "PAUSED",
        "profile": profile,
        "temperature": temperature,
        "target": target,
        "runtime": runtime,
        "totaltime": 8.5 * 3600,
        "heat": 0,
    }


def outcome_state(reason: str, *, temperature: float, target: float, profile: str) -> dict[str, object]:
    """Return one fake post-run state using the shared backend reason text."""
    reason_info = describe_run_reason(
        reason,
        temperature=temperature,
        temp_limit=2350,
        sensor_error_pct=42,
        sensor_error_limit_pct=30,
    )
    return {
        "state": "IDLE",
        "temperature": temperature,
        "target": target,
        "heat": 0,
        "last_run_summary": {
            "profile": profile,
            "reason": reason,
            "reason_text": reason_info["reason_text"],
            "reason_kind": reason_info["reason_kind"],
        },
    }


def show_welcome_sequence(display: KilnDisplay, player: DemoPlayer, frame_delay: float) -> None:
    """Animate the Kiln God startup frames."""
    print("\nStartup animation")
    print("-" * 20)
    for frame_name in STARTUP_FRAME_NAMES:
        player.show(frame_name, display.render_centered_icon_image(frame_name), frame_delay)


def show_prestart_screens(display: KilnDisplay, player: DemoPlayer, screen_seconds: float) -> None:
    """Show ready and scheduled states before a run begins."""
    print("\nReady and waiting")
    print("-" * 20)
    player.show(
        "ready",
        display.render_status_card_image(
            "READY",
            ("cone-6-demo", "72", "Press start"),
            "stop_sign",
        ),
        screen_seconds,
    )
    player.show(
        "waiting",
        display.render_status_card_image(
            "WAITING",
            ("cone-6-demo", "07:00 start", "clock = schedule"),
            "clock",
        ),
        screen_seconds,
    )


def show_firing_transition(display: KilnDisplay, player: DemoPlayer, frame_delay: float) -> None:
    """Show the pottery splash and one flame cycle."""
    print("\nFiring transition")
    print("-" * 20)
    player.show("pottery", display.render_centered_icon_image("pottery"), 1.0)
    for frame_name in FIRING_FLAME_FRAME_NAMES:
        player.show(frame_name, display.render_centered_icon_image(frame_name), frame_delay)


def show_running_states(display: KilnDisplay, player: DemoPlayer, screen_seconds: float) -> None:
    """Show fake live states using the real runtime OLED layout."""
    print("\nLive run states")
    print("-" * 20)
    states = [
        running_state("C6 RAMP", 145, 250, 3 * 60, 1),
        running_state("C6 RAMP", 620, 980, 82 * 60, 1),
        paused_state("C6 HOLD", 1815, 1830, 5.75 * 3600),
        running_state("C6 SOAK", 1831, 1830, 6.1 * 3600, 0),
        running_state("C6 PEAK", 2232, 2235, 7.98 * 3600, 1),
    ]
    for index, state in enumerate(states, start=1):
        player.show(
            f"runtime-{index}",
            display.render_state_image(state),
            screen_seconds,
        )


def show_finish_and_error_screens(display: KilnDisplay, player: DemoPlayer, screen_seconds: float) -> None:
    """Show normal completion plus an error example."""
    print("\nFinish and error examples")
    print("-" * 20)
    player.show(
        "complete",
        display.render_state_image(
            outcome_state(
                "schedule_complete",
                temperature=1640,
                target=0,
                profile="cone-6-demo",
            )
        ),
        screen_seconds,
    )
    player.show(
        "manual-stop",
        display.render_state_image(
            outcome_state(
                "manual_stop_http",
                temperature=812,
                target=1200,
                profile="cone-6-demo",
            )
        ),
        screen_seconds,
    )
    player.show(
        "error",
        display.render_state_image(
            outcome_state(
                "emergency_temp_too_high",
                temperature=2364,
                target=2235,
                profile="cone-6-demo",
            )
        ),
        screen_seconds,
    )


def run_demo(display: KilnDisplay, player: DemoPlayer, startup_delay: float, screen_seconds: float, firing_delay: float) -> None:
    """Run the complete display demo sequence."""
    show_welcome_sequence(display, player, startup_delay)
    show_prestart_screens(display, player, screen_seconds)
    show_firing_transition(display, player, firing_delay)
    show_running_states(display, player, screen_seconds)
    show_finish_and_error_screens(display, player, screen_seconds)
    player.export()


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the display demo."""
    parser = argparse.ArgumentParser(description="Run the integrated kiln OLED demo")
    parser.add_argument(
        "--startup-delay",
        type=float,
        default=0.22,
        help="Seconds to hold each kiln_god startup frame",
    )
    parser.add_argument(
        "--screen-seconds",
        type=float,
        default=1.6,
        help="Seconds to hold each state screen",
    )
    parser.add_argument(
        "--firing-delay",
        type=float,
        default=0.14,
        help="Seconds to hold each pottery flame transition frame",
    )
    parser.add_argument(
        "--preview-dir",
        type=str,
        default="",
        help="Optional directory for exported PNG frames and an animated GIF",
    )
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="Render/export frames without touching OLED hardware",
    )
    return parser


def main() -> None:
    """Run the display demo against hardware or as a preview export."""
    parser = build_parser()
    args = parser.parse_args()

    preview_dir = args.preview_dir.strip() or None
    display = KilnDisplay(headless=args.preview_only)

    if not display.initialized and not args.preview_only and preview_dir:
        print("Display not initialized, falling back to preview-only export")
        display = KilnDisplay(headless=True)

    if not display.initialized and not preview_dir:
        print("ERROR: Display not initialized")
        sys.exit(1)

    player = DemoPlayer(display, preview_dir=preview_dir)

    if display.initialized:
        print("Display initialized successfully")
    else:
        print("Running in preview-only mode")

    try:
        run_demo(
            display,
            player,
            startup_delay=args.startup_delay,
            screen_seconds=args.screen_seconds,
            firing_delay=args.firing_delay,
        )
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)
    except Exception as exc:
        print(f"\nError: {exc}")
        sys.exit(1)
    finally:
        if display.initialized:
            print("\nClearing display...")
            display.clear()
        if preview_dir:
            print(f"Preview exported to {preview_dir}")


if __name__ == "__main__":
    main()
