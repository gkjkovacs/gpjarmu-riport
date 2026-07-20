#!/usr/bin/env python3
"""
Thin wrapper for the HR Középvállalati Magyar Közlöny Havi Riport CLI.

The real CLI lives in `hr_kozlony.cli:app` (the `cli.py` module of the
installed package). This `run.py` exists so the project can be run
without installation:

    python run.py run              # normal run (uses last_run from state DB)
    python run.py seed             # initial 30-day seed run
    python run.py init-db [--force]
    python run.py show-config
    python run.py show-state       # inspect state.db

For full functionality (editable install, `hr-kozlony` console script),
run `pip install -e .` and use the `hr-kozlony` command.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make src/ importable when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from hr_kozlony.cli import app  # noqa: E402

if __name__ == "__main__":
    app()
