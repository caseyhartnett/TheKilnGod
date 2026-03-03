#!/usr/bin/env python3
"""Compatibility wrapper for display updater module."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from thekilngod.display_updater import *  # noqa: F401,F403
