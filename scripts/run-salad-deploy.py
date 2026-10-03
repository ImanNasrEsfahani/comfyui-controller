#!/usr/bin/env python3
"""Load DB-backed active group/image for the existing CLI Salad deployer.

salad-worker/deploy_salad.py is unchanged: no large worker image rebuild.
"""
import json
import os
import runpy
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8100/api/salad/settings"
token = os.environ.get("APP_INTERNAL_TOKEN", "").strip()
if not token:
    raise SystemExit("APP_INTERNAL_TOKEN missing in private .env")
try:
    req = urllib.request.Request(API, headers={"X-Internal-Token": token})
    with urllib.request.urlopen(req, timeout=10) as response:
        active = json.load(response)["active"]
except (OSError, KeyError, ValueError) as exc:
    raise SystemExit(
        "Cannot read current group settings from Backend. "
        "Start Backend and verify /health first. Cause: " + type(exc).__name__
    ) from None
for field, name in (("image", "SALAD_IMAGE"),
                    ("group_name", "SALAD_CONTAINER_GROUP_NAME"),
                    ("display_name", "SALAD_CONTAINER_GROUP_DISPLAY_NAME")):
    value = active.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit("Invalid DB-backed deployment setting: " + field)
    os.environ[name] = value.strip()

root = Path(__file__).resolve().parents[1]
runpy.run_path(str(root / "salad-worker/deploy_salad.py"), run_name="__main__")
