"""Non-secret mutable deployment settings, persisted inside the existing SQLite volume.

The active group is separate from a draft. Saving a draft NEVER redirects running
instances. A new group becomes active only after the Salad deploy succeeds.
"""
import json
import os
from . import db

FIELDS = ("image", "group_name", "display_name")
ENV_KEYS = {
    "image": "SALAD_IMAGE",
    "group_name": "SALAD_CONTAINER_GROUP_NAME",
    "display_name": "SALAD_CONTAINER_GROUP_DISPLAY_NAME",
}


def _read(c, key):
    row = c.execute("SELECT value FROM controller_settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


def _write(c, key, value):
    c.execute(
        "INSERT INTO controller_settings(key,value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )


def seed():
    """One-time migration from the PRIVATE existing .env, never overwrite DB."""
    with db.connect() as c:
        if _read(c, "salad_active") is not None:
            if _read(c, "salad_draft") is None:
                _write(c, "salad_draft", _read(c, "salad_active"))
            return
        values = {field: os.environ.get(env, "").strip()
                  for field, env in ENV_KEYS.items()}
        absent = [ENV_KEYS[field] for field in FIELDS if not values[field]]
        if absent:
            raise RuntimeError(
                "First-time settings migration requires existing private .env values: "
                + ", ".join(absent)
                + ". Restore from the .env backup, start once, then remove these keys."
            )
        _write(c, "salad_active", values)
        _write(c, "salad_draft", values)


def active():
    with db.connect() as c:
        result = _read(c, "salad_active")
    if result is None:
        raise RuntimeError("Runtime settings are not initialized; restart backend to migrate .env")
    return result


def snapshot():
    with db.connect() as c:
        current = _read(c, "salad_active")
        draft = _read(c, "salad_draft")
        candidate = _read(c, "salad_provisioning")
    if current is None or draft is None:
        raise RuntimeError("Runtime settings are not initialized")
    return {"active": current, "draft": draft, "provisioning": candidate,
            "has_changes": current != draft}


def save_draft(value):
    selected = {field: value[field] for field in FIELDS}
    with db.connect() as c:
        previous = _read(c, "salad_draft")
        _write(c, "salad_draft", selected)
        # Preserve an in-flight candidate when Save is repeated unchanged:
        # a later Deploy can reuse it rather than creating an extra group.
        if previous != selected:
            _write(c, "salad_provisioning", None)
    return snapshot()


def provisioning(value):
    with db.connect() as c:
        _write(c, "salad_provisioning", value)


def activate(value):
    with db.connect() as c:
        _write(c, "salad_active", {field: value[field] for field in FIELDS})
        _write(c, "salad_draft", {field: value[field] for field in FIELDS})
        _write(c, "salad_provisioning", None)
    return snapshot()
