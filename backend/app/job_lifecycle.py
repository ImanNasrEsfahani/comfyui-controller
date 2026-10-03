"""Helpers for job timeout display and reconstructing editable legacy drafts."""
from datetime import datetime, timezone
import re
from urllib.parse import urlparse, unquote

from .config import settings

TERMINAL = frozenset({"succeeded", "failed", "cancelled", "submit_failed"})
RETRYABLE = frozenset({"failed", "cancelled", "submit_failed"})
IMAGE_KEY = re.compile(r"^input\.image_\d+$")
PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_.:-]+)\}\}")


def age_minutes(when, *, now=None):
    try:
        created = datetime.fromisoformat(when.replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        return max(0, (current - created).total_seconds() / 60)
    except (TypeError, AttributeError, ValueError):
        return 0


def stale_message(minutes):
    return (f"No terminal Salad result after {minutes} minutes. The remote job "
            "may still be queued or running; this is not a confirmed failure.")


def recover_image_ref(value):
    """Recover only our own signed upload URL; never trust an arbitrary host."""
    if not isinstance(value, str):
        return value
    if value.startswith(f"s3://{settings.r2_bucket}/inputs/"):
        return value
    if not value.startswith("https://"):
        return ""
    parsed = urlparse(value)
    endpoint = urlparse(settings.r2_endpoint_url)
    if parsed.hostname != endpoint.hostname:
        return ""
    path = unquote(parsed.path).lstrip("/")
    bucket_prefix = settings.r2_bucket + "/"
    if path.startswith(bucket_prefix):
        path = path[len(bucket_prefix):]
    if not path.startswith("inputs/") or "/../" in path:
        return ""
    return f"s3://{settings.r2_bucket}/{path}"


def legacy_draft(workflow_template, rendered_prompt):
    """Best effort for pre-migration jobs; no guessing missing values."""
    found = {}
    def walk(template, rendered):
        if isinstance(template, dict) and isinstance(rendered, dict):
            for key, value in template.items():
                if key in rendered:
                    walk(value, rendered[key])
        elif isinstance(template, list) and isinstance(rendered, list):
            for a, b in zip(template, rendered):
                walk(a, b)
        elif isinstance(template, str):
            match = PLACEHOLDER.fullmatch(template)
            if match:
                key = match.group(1)
                if IMAGE_KEY.match(key):
                    found[key] = recover_image_ref(rendered)
                else:
                    found[key] = rendered
                return
            names = PLACEHOLDER.findall(template)
            if len(names) == 1 and isinstance(rendered, str):
                parts = template.split("{{" + names[0] + "}}")
                if (rendered.startswith(parts[0]) and rendered.endswith(parts[1])
                        and len(rendered) >= len(parts[0]) + len(parts[1])):
                    end = len(rendered) - len(parts[1]) if parts[1] else len(rendered)
                    found[names[0]] = rendered[len(parts[0]):end]
    walk(workflow_template or {}, rendered_prompt or {})
    return found
