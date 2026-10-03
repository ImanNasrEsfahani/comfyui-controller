#!/usr/bin/env python3
"""Safely rebuild root .env from .env.example, retaining PRIVATE secrets.

Requires existing .env with valid single-line credentials. Backups are saved
outside the repository. Fails without modifying .env if credentials are absent
or look truncated. Never print tokens and never connect to external services.
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import os
import re
import secrets
import shutil

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".env.example"
TARGET = ROOT / ".env"
SENSITIVE = (
    "SALAD_API_KEY",
    "R2_ENDPOINT_URL",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
)
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def parse(raw, name, *, strict):
    values = {}
    for lineno, line in enumerate(raw.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = KEY_RE.fullmatch(line)
        if not match:
            if strict:
                raise ValueError(f"Invalid {name} line {lineno}")
            continue  # Ignore broken legacy lines: rebuild from clean template.
        key, value = match.groups()
        if strict and key in values:
            raise ValueError(f"Duplicate {key} in {name}")
        values[key] = value
    return values


def unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def clean_secret(name, raw):
    value = unquote(raw or "")
    if not value or any(ch.isspace() for ch in value) or "#" in value:
        raise ValueError(f"{name} is missing or malformed in the old .env")
    if name == "SALAD_API_KEY" and not re.fullmatch(r"salad_[A-Za-z0-9_-]{25,}", value):
        raise ValueError(f"{name} appears incomplete in the old .env")
    if name == "R2_ENDPOINT_URL":
        url = urlparse(value)
        if url.scheme != "https" or not url.hostname or not url.hostname.endswith(".r2.cloudflarestorage.com"):
            raise ValueError(f"{name} is not a valid R2 endpoint in the old .env")
    if name == "R2_ACCESS_KEY_ID" and not re.fullmatch(r"[A-Za-z0-9]{20,128}", value):
        raise ValueError(f"{name} appears incomplete in the old .env")
    if name == "R2_SECRET_ACCESS_KEY" and not re.fullmatch(r"[A-Za-z0-9/+_=-]{32,256}", value):
        raise ValueError(f"{name} appears incomplete in the old .env")
    return value


def main():
    if not TEMPLATE.is_file() or not TARGET.is_file():
        raise SystemExit("Both .env.example and the old .env must exist; nothing changed")
    template_raw = TEMPLATE.read_text(encoding="utf-8")
    previous_raw = TARGET.read_text(encoding="utf-8")
    template = parse(template_raw, ".env.example", strict=True)
    previous = parse(previous_raw, ".env", strict=False)
    try:
        recovered = {key: clean_secret(key, previous.get(key)) for key in SENSITIVE}
        old_admin = unquote(previous.get("APP_INTERNAL_TOKEN", ""))
        if len(old_admin) >= 32 and not any(ch.isspace() for ch in old_admin):
            recovered["APP_INTERNAL_TOKEN"] = old_admin
            admin_generated = False
        else:
            recovered["APP_INTERNAL_TOKEN"] = secrets.token_hex(32)
            admin_generated = True
        hf = unquote(previous.get("HF_TOKEN", ""))
        if hf:
            if any(ch.isspace() for ch in hf) or "#" in hf:
                raise ValueError("HF_TOKEN is malformed in the old .env")
            recovered["HF_TOKEN"] = hf
        unknown = set(recovered) - set(template)
        if unknown:
            raise ValueError("These settings are absent from .env.example: " + ", ".join(sorted(unknown)))
    except ValueError as exc:
        raise SystemExit(f"ABORTED without touching .env: {exc}") from None

    # A backup is created BEFORE any replacement, outside the Git repository.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup = Path.home() / f"comfyui-env-before-rebuild-{stamp}-{secrets.token_hex(3)}.bak"
    shutil.copyfile(TARGET, backup)
    backup.chmod(0o600)

    output = []
    for line in template_raw.splitlines():
        match = KEY_RE.fullmatch(line)
        if match and match.group(1) in recovered:
            key = match.group(1)
            output.append(key + "=" + recovered[key])
        else:
            output.append(line)
    content = "\n".join(output) + "\n"
    temp = ROOT / (".env.pending-" + secrets.token_hex(5))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        parse(content, "new .env", strict=True)
        os.replace(temp, TARGET)
        TARGET.chmod(0o600)
    finally:
        temp.unlink(missing_ok=True)
    print("Private .env successfully rebuilt from .env.example.")
    print("Old .env saved securely at:", backup)
    print("Existing Salad and R2 credentials preserved without printing them.")
    if admin_generated:
        print("A new strong APP_INTERNAL_TOKEN was generated; read it locally from .env to log in.")
    print("Rotate the previously shared Salad/R2 keys as soon as possible.")


if __name__ == "__main__":
    main()
