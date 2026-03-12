"""
SSD1309 OLED display module for kiln status and icon rendering.

The runtime display uses a compact icon-first layout for normal status screens
and supports short startup / firing transition animations.
"""

import logging
import re
import time
from pathlib import Path

import config

try:
    from PIL import Image, ImageDraw, ImageFont

    PIL_AVAILABLE = True
except Exception as e:
    PIL_AVAILABLE = False
    PIL_IMPORT_ERROR = e

try:
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1309

    LUMA_AVAILABLE = True
except Exception as e:
    LUMA_AVAILABLE = False
    LUMA_IMPORT_ERROR = e

log = logging.getLogger("kiln-controller.display")

DEFAULT_ICON_NAMES = (
    "clock",
    "flame",
    "snowflake",
    "stop_sign",
    "pottery",
    "pottery_flame_1",
    "pottery_flame_2",
    "pottery_flame_3",
    "pottery_flame_4",
    "pottery_flame_5",
)

STARTUP_FRAME_NAMES = tuple(f"kiln_god_{index}" for index in range(6))
FIRING_FLAME_FRAME_NAMES = tuple(f"pottery_flame_{index}" for index in range(1, 6))


class KilnDisplay:
    """Manage the SSD1309 OLED display and its icon-based layouts."""

    def __init__(
        self,
        width=None,
        height=None,
        i2c_address=None,
        i2c_port=None,
        *,
        headless=False,
    ):
        """
        Initialize the display.

        Args:
            width: Display width in pixels (default from config or 128)
            height: Display height in pixels (default from config or 64)
            i2c_address: I2C address of the display (default from config or 0x3C)
            i2c_port: I2C port number (default from config or 1)
            headless: Skip hardware initialization but keep rendering helpers available
        """
        config_width = getattr(config, "display_width", 128)
        config_height = getattr(config, "display_height", 64)
        config_address = getattr(config, "display_i2c_address", 0x3C)
        config_port = getattr(config, "display_i2c_port", 1)
        config_enabled = getattr(config, "display_enabled", True)

        self.width = width if width is not None else config_width
        self.height = height if height is not None else config_height
        address = i2c_address if i2c_address is not None else config_address
        port = i2c_port if i2c_port is not None else config_port

        self.headless = bool(headless)
        self.device = None
        self.initialized = False
        self.unavailable_reason = None
        self.icon_cache = {}
        self.font_small = self._load_font(10)
        self.font_medium = self._load_font(14)
        self.font_large = self._load_font(22)

        if not PIL_AVAILABLE:
            self.unavailable_reason = f"display image support missing: {PIL_IMPORT_ERROR}"
            log.warning(self.unavailable_reason)
            return

        self.preload_icons(DEFAULT_ICON_NAMES)

        if self.headless:
            return

        if not config_enabled:
            log.info("Display disabled in config")
            return

        if not LUMA_AVAILABLE:
            self.unavailable_reason = f"display dependencies missing: {LUMA_IMPORT_ERROR}"
            log.warning(self.unavailable_reason)
            return

        try:
            serial = i2c(port=port, address=address)
            self.device = ssd1309(serial, width=self.width, height=self.height)
            self.device.clear()
            self.initialized = True
            log.info("SSD1309 display initialized successfully at address 0x%02X", address)
        except Exception as e:
            log.warning("Failed to initialize display: %s", e)
            self.initialized = False

    @staticmethod
    def _icon_directories():
        module_dir = Path(__file__).resolve().parent
        return [
            module_dir / "images" / "hex",
            module_dir.parents[1] / "images" / "hex",
        ]

    @staticmethod
    def _load_font(size):
        if not PIL_AVAILABLE:
            return None
        for candidate in (
            "DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
        ):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def preload_icons(self, icon_names):
        """Warm the icon cache so runtime animation does not hit the filesystem."""
        for icon_name in icon_names:
            self.get_icon(icon_name)

    def format_temperature(self, temp, scale="f"):
        """Format a temperature with an explicit degree suffix."""
        if temp is None:
            return "---"
        if scale.lower() == "f":
            return f"{temp:.0f}°F"
        return f"{temp:.0f}°C"

    @staticmethod
    def format_compact_temperature(temp):
        """Format a temperature without a degree or unit label."""
        if temp is None:
            return "---"
        try:
            return f"{float(temp):.0f}"
        except (TypeError, ValueError):
            return "---"

    def format_time(self, seconds):
        """Format seconds as HH:MM:SS or MM:SS."""
        if seconds is None or seconds < 0:
            return "--:--"

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    @staticmethod
    def _truncate(text, max_chars):
        if text is None:
            return ""
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1] + "…"

    def _text_width(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _wrap_text(self, draw, text, font, max_width, max_lines=2):
        words = str(text or "").split()
        if not words:
            return []

        lines = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if self._text_width(draw, candidate, font) <= max_width:
                current = candidate
                continue
            lines.append(current)
            current = word
            if len(lines) >= max_lines - 1:
                break

        if len(lines) < max_lines:
            lines.append(current)

        if len(lines) > max_lines:
            lines = lines[:max_lines]

        if words and len(lines) == max_lines:
            rendered = " ".join(lines).split()
            if len(rendered) < len(words):
                lines[-1] = self._truncate(lines[-1], max(3, len(lines[-1]) - 1))
        return lines

    def create_blank_image(self):
        """Return an empty monochrome image sized for the display."""
        if not PIL_AVAILABLE:
            raise RuntimeError("Pillow is required for display rendering")
        return Image.new("1", (self.width, self.height), 0)

    def render_centered_icon_image(self, icon_name):
        """Return a frame with one icon centered on the display."""
        image = self.create_blank_image()
        draw = ImageDraw.Draw(image)
        icon = self.get_icon(icon_name)
        if icon:
            x = (self.width - icon.width) // 2
            y = (self.height - icon.height) // 2
            draw.bitmap((x, y), icon, fill="white")
        return image

    def display_image(self, image):
        """Send a pre-rendered image to the OLED if hardware is active."""
        if not self.initialized or self.device is None:
            return False
        try:
            self.device.display(image)
            return True
        except Exception as e:
            log.error("Error displaying image: %s", e)
            return False

    def clear(self):
        """Clear the physical display."""
        if not self.initialized or self.device is None:
            return
        try:
            self.device.clear()
        except Exception as e:
            log.error("Error clearing display: %s", e)

    def render_message_image(self, message, line=0):
        """Render a simple text-only message frame."""
        image = self.create_blank_image()
        draw = ImageDraw.Draw(image)
        y_pos = line * 12
        draw.text((0, y_pos), str(message)[:21], fill="white", font=self.font_small)
        return image

    def show_message(self, message, line=0):
        """Display a simple text message on the OLED."""
        if not PIL_AVAILABLE:
            return
        self.display_image(self.render_message_image(message, line=line))

    def _draw_icon(self, draw, icon_name, x, y):
        icon = self.get_icon(icon_name)
        if icon:
            draw.bitmap((x, y), icon, fill="white")
            return icon.width
        return 0

    def _draw_header(self, draw, title, icon_name):
        icon_width = self._draw_icon(draw, icon_name, 0, 0)
        title_x = 24 if icon_width else 0
        draw.text(
            (title_x, 4),
            self._truncate(title, 15),
            fill="white",
            font=self.font_small,
        )
        draw.line((0, 20, self.width - 1, 20), fill="white")

    def _select_state_icon(self, oven_state):
        state = str(oven_state.get("state", "IDLE") or "IDLE")
        heat = float(oven_state.get("heat", 0) or 0)
        last_summary = oven_state.get("last_run_summary") or {}
        reason_kind = last_summary.get("reason_kind") or oven_state.get("status_reason_kind")
        if state == "PAUSED":
            return "clock"
        if state == "RUNNING":
            return "flame" if heat > 0 else "snowflake"
        if reason_kind == "complete":
            return "snowflake"
        return "stop_sign"

    def _render_running_image(self, oven_state):
        image = self.create_blank_image()
        draw = ImageDraw.Draw(image)
        state = str(oven_state.get("state", "RUNNING") or "RUNNING")
        profile = oven_state.get("profile")
        temp = self.format_compact_temperature(oven_state.get("temperature"))
        target = self.format_compact_temperature(oven_state.get("target"))
        runtime = float(oven_state.get("runtime", 0) or 0)
        totaltime = float(oven_state.get("totaltime", 0) or 0)
        time_value = self.format_time(max(0.0, totaltime - runtime) if totaltime > 0 else runtime)

        title = "PAUSED" if state == "PAUSED" else (profile or state)
        self._draw_header(draw, title, self._select_state_icon(oven_state))

        temp_width = self._text_width(draw, temp, self.font_large)
        draw.text(
            ((self.width - temp_width) / 2, 20),
            temp,
            fill="white",
            font=self.font_large,
        )

        target_text = f"*{target}"
        draw.text((0, 46), target_text, fill="white", font=self.font_medium)
        clock_x = 58
        self._draw_icon(draw, "clock", clock_x, 42)
        draw.text((82, 46), time_value, fill="white", font=self.font_medium)
        return image

    def _render_outcome_image(self, oven_state):
        image = self.create_blank_image()
        draw = ImageDraw.Draw(image)
        summary = oven_state.get("last_run_summary") or {}
        reason_kind = summary.get("reason_kind") or oven_state.get("status_reason_kind") or "info"
        reason_text = (
            summary.get("reason_text") or oven_state.get("status_reason_text") or "Kiln idle"
        )
        profile = summary.get("profile") or oven_state.get("profile")
        temp = self.format_compact_temperature(oven_state.get("temperature"))
        target = self.format_compact_temperature(oven_state.get("target"))

        title = {
            "complete": "DONE",
            "error": "ERROR",
            "stopped": "STOPPED",
        }.get(reason_kind, "READY")

        self._draw_header(draw, title, self._select_state_icon(oven_state))
        if profile:
            draw.text(
                (0, 22),
                self._truncate(profile, 21),
                fill="white",
                font=self.font_small,
            )
        draw.text(
            (0, 33),
            self._truncate(f"{temp}   *{target}", 21),
            fill="white",
            font=self.font_small,
        )
        wrapped = self._wrap_text(draw, reason_text, self.font_small, self.width, max_lines=2)
        for index, line in enumerate(wrapped):
            draw.text(
                (0, 44 + index * 10),
                self._truncate(line, 21),
                fill="white",
                font=self.font_small,
            )
        return image

    def _render_idle_image(self, oven_state):
        image = self.create_blank_image()
        draw = ImageDraw.Draw(image)
        temp = self.format_compact_temperature(oven_state.get("temperature"))
        title = oven_state.get("profile") or "READY"
        self._draw_header(draw, title, "stop_sign")
        temp_width = self._text_width(draw, temp, self.font_large)
        draw.text(
            ((self.width - temp_width) / 2, 20),
            temp,
            fill="white",
            font=self.font_large,
        )
        draw.text((0, 48), "Waiting for start", fill="white", font=self.font_small)
        return image

    def render_status_card_image(self, title, lines, icon_name):
        """Render a simple small-icon status card with up to three detail lines."""
        image = self.create_blank_image()
        draw = ImageDraw.Draw(image)
        self._draw_header(draw, str(title), icon_name)
        for index, line in enumerate(list(lines)[:3]):
            draw.text(
                (0, 24 + index * 12),
                self._truncate(str(line), 21),
                fill="white",
                font=self.font_small,
            )
        return image

    def render_state_image(self, oven_state, temp_scale="f"):
        """Render the current kiln state into a display image."""
        del temp_scale  # Layout uses compact numeric values without a unit suffix.
        state = str(oven_state.get("state", "IDLE") or "IDLE")
        if state in {"RUNNING", "PAUSED"}:
            return self._render_running_image(oven_state)
        if oven_state.get("last_run_summary") or oven_state.get("status_reason_text"):
            return self._render_outcome_image(oven_state)
        return self._render_idle_image(oven_state)

    def update(self, oven_state, temp_scale="f"):
        """Render and display the current oven state."""
        if not PIL_AVAILABLE:
            return
        try:
            image = self.render_state_image(oven_state, temp_scale=temp_scale)
            self.display_image(image)
        except Exception as e:
            log.error("Error updating display: %s", e)

    def show_startup_sequence(self, loops=1, frame_delay=0.12):
        """Play the Kiln God startup frames on the OLED."""
        self.preload_icons(STARTUP_FRAME_NAMES)
        for _ in range(max(1, int(loops))):
            for frame_name in STARTUP_FRAME_NAMES:
                self.display_image(self.render_centered_icon_image(frame_name))
                time.sleep(frame_delay)

    def show_firing_transition(
        self,
        pottery_hold_seconds=1.0,
        frame_delay=0.14,
        cycles=1,
    ):
        """Play the pottery splash followed by the flame animation."""
        self.preload_icons(("pottery", *FIRING_FLAME_FRAME_NAMES))
        self.display_image(self.render_centered_icon_image("pottery"))
        time.sleep(max(0.0, pottery_hold_seconds))
        for _ in range(max(1, int(cycles))):
            for frame_name in FIRING_FLAME_FRAME_NAMES:
                self.display_image(self.render_centered_icon_image(frame_name))
                time.sleep(frame_delay)

    @staticmethod
    def load_icon_from_hex(icon_name):
        """
        Load an icon from a hex file in the packaged or repository icon directories.

        Args:
            icon_name: Name of icon file (without .hex extension), e.g., 'flame', 'clock'

        Returns:
            PIL Image object or None if file not found
        """
        if not PIL_AVAILABLE:
            log.warning("Cannot load icon %s because Pillow is unavailable", icon_name)
            return None

        icon_path = next(
            (
                path / f"{icon_name}.hex"
                for path in KilnDisplay._icon_directories()
                if (path / f"{icon_name}.hex").exists()
            ),
            None,
        )

        if icon_path is None:
            searched_paths = ", ".join(str(path) for path in KilnDisplay._icon_directories())
            log.warning("Icon file not found for %s. Searched: %s", icon_name, searched_paths)
            return None

        try:
            with open(icon_path, encoding="utf-8") as f:
                hex_text = f.read()

            width, height = 16, 16
            dimension_pattern = r"(\d+)x(\d+)px"
            for line in hex_text.split("\n"):
                match = re.search(dimension_pattern, line, re.IGNORECASE)
                if match:
                    width = int(match.group(1))
                    height = int(match.group(2))
                    break

            lines = [line for line in hex_text.split("\n") if not line.strip().startswith("//")]
            hex_text = "\n".join(lines)
            hex_pattern = r"0x([0-9a-fA-F]+)"
            matches = re.findall(hex_pattern, hex_text)
            hex_data = [int(hex_val, 16) for hex_val in matches]

            bytes_per_row = (width + 7) // 8
            expected_bytes = bytes_per_row * height
            if len(hex_data) != expected_bytes:
                log.warning(
                    "Hex data size mismatch: expected %s bytes, got %s",
                    expected_bytes,
                    len(hex_data),
                )
                if len(hex_data) < expected_bytes:
                    hex_data.extend([0] * (expected_bytes - len(hex_data)))
                else:
                    hex_data = hex_data[:expected_bytes]

            image = Image.new("1", (width, height), 0)
            for y in range(height):
                row_offset = y * bytes_per_row
                row_bytes = hex_data[row_offset : row_offset + bytes_per_row]
                for byte_index, byte_val in enumerate(row_bytes):
                    for bit in range(7, -1, -1):
                        x = byte_index * 8 + (7 - bit)
                        if x >= width:
                            break
                        if byte_val & (1 << bit):
                            image.putpixel((x, y), 1)
            return image
        except Exception as e:
            log.error("Error loading icon %s: %s", icon_name, e)
            return None

    def get_icon(self, icon_name):
        """Return a cached icon image for drawing."""
        if icon_name not in self.icon_cache:
            self.icon_cache[icon_name] = self.load_icon_from_hex(icon_name)
        return self.icon_cache.get(icon_name)


def example_usage():
    """Example of how to use the display."""
    display = KilnDisplay(headless=True)
    example_state = {
        "temperature": 1250,
        "target": 1300,
        "state": "RUNNING",
        "profile": "Cone 6 Glaze",
        "runtime": 3600,
        "totaltime": 7200,
        "heat_rate": 150,
        "heat": 1,
    }
    return display.render_state_image(example_state, temp_scale="f")
