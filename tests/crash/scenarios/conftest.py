"""Make the crash harness importable from the scenario modules."""

from __future__ import annotations

import sys
from pathlib import Path

_HARNESS_DIR = str(Path(__file__).resolve().parents[1])
if _HARNESS_DIR not in sys.path:
    sys.path.insert(0, _HARNESS_DIR)
