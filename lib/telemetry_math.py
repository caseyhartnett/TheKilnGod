"""Compatibility wrapper for legacy imports."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from thekilngod.telemetry_math import *  # noqa: F401,F403
