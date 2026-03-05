#!/usr/bin/env python3
"""CLI wrapper for `thekilngod.firing_analyzer`.

This keeps script-based usage (`python scripts/firing_analyzer.py ...`) while
reusing the typed implementation in `src/thekilngod/firing_analyzer.py`.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))


def _main() -> int:
    """Load and run the analyzer entrypoint from the package module."""
    from thekilngod.firing_analyzer import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_main())
