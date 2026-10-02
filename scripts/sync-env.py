#!/usr/bin/env python3
"""Append missing example keys to the PRIVATE root .env without overwriting values.

Creates a 0600 backup OUTSIDE the repository before any change. Does not
print credentials, push to GitHub, or remove legacy variables automatically.
"""
from datetime import datetime, timezone
from pathlib import Path
import os
import re
import shutil

root = Path(__file__).resolve().parents[1]
source = root / ".env.example"
target = root / ".env"
if not target.is_file():
    raise SystemExit("Private .env missing; create it safely from .env.example and add credentials")

pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")

def read_keys(raw, where):
    result = {}
    for line in raw.splitlines():
        match = pattern.match(line)
        if match:
            key = match.group(1)
            if key in result:
                raise SystemExit(f"Duplicate key {key} found in {where}; fix it before continuing")
            result[key] = line
    return result

example = read_keys(source.read_text(encoding="utf-8"), source)
current_raw = target.read_text(encoding="utf-8")
current = read_keys(current_raw, target)
missing = [line for key, line in example.items() if key not in current]
if not missing:
    print(".env already contains all example keys; no changes made.")
else:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path.home() / f".comfyui-controller.env.backup-{stamp}"
    if backup.exists():
        raise SystemExit("Backup destination already exists; retry in a moment")
    shutil.copy2(target, backup)
    os.chmod(backup, 0o600)
    with target.open("a", encoding="utf-8") as output:
        if current_raw and not current_raw.endswith("\n"):
            output.write("\n")
        output.write("\n# Added from .env.example (review before deployment)\n")
        output.write("\n".join(missing) + "\n")
    os.chmod(target, 0o600)
    print(f"Added {len(missing)} missing configuration keys to private .env")
    print("Backup saved outside the repository:", backup)

legacy = sorted(set(current) & {
    "SALAD_QUEUE_PREFIX", "SALAD_CONTAINER_GROUP_PREFIX",
    "SALAD_DEFAULT_PRIORITY", "SALAD_GPU_NAMES",
})
if legacy:
    print("Unused legacy keys (remove after checking your configuration):", ", ".join(legacy))
print("Keep existing SALAD_API_KEY and R2 credentials; verify required values before --apply.")
