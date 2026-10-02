#!/usr/bin/env python3
"""One-time, safe edit of the existing frontend/src/App.jsx in a full checkout.

The rest of App.jsx is retained byte-for-byte. Safe to run more than once.
Use after extracting the replacement package OVER the repository root.
"""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / "frontend" / "src" / "App.jsx"
source = target.read_text(encoding="utf-8")

old_options = '''const PRIORITY_OPTIONS = [
  { value: "high", label: "High", help: "Highest availability, highest cost" },
  { value: "medium", label: "Medium — Default", help: "Balanced availability and cost" },
  { value: "low", label: "Low", help: "Lower cost, more interruptions" },
  { value: "batch", label: "Batch / Lowest", help: "Lowest cost; may wait for capacity" }
];'''
new_options = '''const PRIORITY_OPTIONS = [
  { value: "medium", label: "Medium — RTX 5090", help: "Only the Medium GPU Queue is enabled." }
];'''

if old_options in source:
    if source.count(old_options) != 1:
        raise SystemExit("Unexpected number of priority blocks; not editing frontend")
    source = source.replace(old_options, new_options)
elif new_options not in source:
    raise SystemExit("Cannot find the expected priority block. Inspect App.jsx manually.")

# Preserve existing UI; its select now contains one Medium option only.
target.write_text(source, encoding="utf-8")
print(f"Medium-only frontend ready: {target}")
