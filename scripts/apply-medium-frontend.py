#!/usr/bin/env python3
"""Backward-compatible launcher for the environment-driven source migration."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).with_name("apply-env-source.py")), run_name="__main__")
