#!/usr/bin/env python3
"""Idempotent, single-Medium Salad Job Queue + GPU Container Group deployment.

Default: read-only inspection. --apply creates missing resources and repairs
supported configuration drift on the existing Medium group. It NEVER deletes
other groups or queues, changes replicas of an existing group, or starts a GPU.
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request

BASE = "https://api.salad.com/api/public"
USER_AGENT = "comfyui-controller/medium-only-1.0"
PRIORITY = "medium"
GPU_NAME = "RTX 5090 (32 GB)"
QUEUE_NAME = "qwen-comfyui-medium"
GROUP_NAME = "qwen-comfyui-fp8-medium"
RESOURCE_SPEC = {
    "cpu": 4,
    "memory": 30 * 1024,  # Salad's RAM field is expressed in MB.
    "shm_size": 2048,    # MB
    "storage_amount": 100 * 1024 ** 3,  # bytes
}
SENSITIVE_KEYS = {
    "aws_access_key_id", "aws_secret_access_key", "hf_token", "salad_api_key",
    "r2_access_key_id", "r2_secret_access_key",
}


def env(name, default=None, required=False):
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing {name}")
    return value


API_KEY = env("SALAD_API_KEY", required=True)
ORG = env("SALAD_ORG", "imanprojects")
PROJECT = env("SALAD_PROJECT", "comfy")
IMAGE = env("SALAD_IMAGE", "ghcr.io/imannasresfahani/comfyui-controller-salad-worker:fp8-baked")
SETTLE_TIMEOUT = int(env("SALAD_CONFIG_SETTLE_TIMEOUT", "600"))
SETTLE_POLL_SECONDS = int(env("SALAD_CONFIG_SETTLE_POLL_SECONDS", "5"))


def validate_configuration():
    # Prevent an old .env silently directing the backend to a different queue.
    expected = {
        "SALAD_QUEUE_PREFIX": "qwen-comfyui",
        "SALAD_CONTAINER_GROUP_PREFIX": "qwen-comfyui-fp8",
        "SALAD_DEFAULT_PRIORITY": PRIORITY,
    }
    for key, value in expected.items():
        actual = env(key, value)
        if actual != value:
            raise SystemExit(f"{key} must be {value!r}; got {actual!r}")
    if int(env("SALAD_MIN_REPLICAS", "0")) != 0:
        raise SystemExit("SALAD_MIN_REPLICAS must be 0 (scale-to-zero)")
    if int(env("SALAD_MAX_REPLICAS", "1")) != 1:
        raise SystemExit("SALAD_MAX_REPLICAS must be 1")
    if int(env("SALAD_INITIAL_REPLICAS", "0")) != 0:
        raise SystemExit("SALAD_INITIAL_REPLICAS must be 0 to avoid immediate GPU cost")
    if SETTLE_TIMEOUT <= 0 or SETTLE_POLL_SECONDS <= 0:
        raise SystemExit("Settle timeout and polling interval must be positive")


def request(method, path, body=None, *, allow_404=False, content_type="application/json"):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    url = BASE + path
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Salad-Api-Key": API_KEY,
            "Content-Type": content_type,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        if allow_404 and exc.code == 404:
            return None
        raise RuntimeError(f"{method} {url} -> {exc.code}: {raw}") from exc


def redact_secrets(value):
    if isinstance(value, dict):
        return {
            k: "***REDACTED***" if k.lower() in SENSITIVE_KEYS and v else redact_secrets(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    return value


def project_path():
    return f"/organizations/{ORG}/projects/{PROJECT}"


def queue_path():
    return f"{project_path()}/queues/{QUEUE_NAME}"


def group_path():
    return f"{project_path()}/containers/{GROUP_NAME}"


def get_queue():
    return request("GET", queue_path(), allow_404=True)


def get_group():
    return request("GET", group_path(), allow_404=True)


def select_gpu():
    data = request("GET", f"/organizations/{ORG}/gpu-classes")
    items = data if isinstance(data, list) else data.get("items", [])
    normalized = lambda name: " ".join(str(name).strip().lower().split())
    matches = [gpu for gpu in items if normalized(gpu.get("name")) == normalized(GPU_NAME)]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one GPU class {GPU_NAME!r}; found {len(matches)}")
    return matches[0]["id"]


def autoscaler_payload():
    return {
        "min_replicas": 0,
        "max_replicas": 1,
        "desired_queue_length": int(env("SALAD_DESIRED_QUEUE_LENGTH", "1")),
        "polling_period": int(env("SALAD_POLLING_PERIOD", "30")),
        "max_upscale_per_minute": 1,
        "max_downscale_per_minute": 1,
    }


def readiness_probe_payload():
    return {
        "http": {"path": "/ready", "port": 3000, "scheme": "http", "headers": []},
        "initial_delay_seconds": 30,
        "period_seconds": 30,
        "timeout_seconds": 5,
        "success_threshold": 1,
        "failure_threshold": 20,
    }


def startup_probe_payload():
    return {
        "http": {"path": "/health", "port": 3000, "scheme": "http", "headers": []},
        "initial_delay_seconds": 120,
        "period_seconds": 90,
        "timeout_seconds": 5,
        "success_threshold": 1,
        "failure_threshold": 20,
    }


def environment_payload():
    values = {
        "MANIFEST": "/opt/qvr-salad/manifest.yaml",
        "PORT": "3000",
        "LRU_CACHE_SIZE_GB": "40",
        "SALAD_LOG_LEVEL": "info",
        "READY_TIMEOUT_SECONDS": "1800",
        "STARTUP_CHECK_MAX_TRIES": "360",
        "STARTUP_CHECK_INTERVAL_S": "5",
        "AWS_ACCESS_KEY_ID": env("R2_ACCESS_KEY_ID", required=True),
        "AWS_SECRET_ACCESS_KEY": env("R2_SECRET_ACCESS_KEY", required=True),
        "AWS_REGION": env("R2_REGION", "auto"),
        "AWS_ENDPOINT_URL_S3": env("R2_ENDPOINT_URL", required=True),
        "AWS_ENDPOINT_URL": env("R2_ENDPOINT_URL", required=True),
    }
    token = env("HF_TOKEN", "")
    if token:
        values["HF_TOKEN"] = token
    return values


def queue_payload():
    return {"name": QUEUE_NAME, "display_name": "Qwen ComfyUI Medium Jobs"}


def group_payload(gpu_id):
    return {
        "name": GROUP_NAME,
        "display_name": "Qwen ComfyUI Medium",
        "container": {
            "image": IMAGE,
            "resources": {**RESOURCE_SPEC, "gpu_classes": [gpu_id]},
            "environment_variables": environment_payload(),
            "priority": PRIORITY,
        },
        "replicas": 0,
        "restart_policy": "always",
        "autostart_policy": True,
        "queue_connection": {"path": "/prompt", "port": 3000, "queue_name": QUEUE_NAME},
        "queue_autoscaler": autoscaler_payload(),
        "readiness_probe": readiness_probe_payload(),
        "startup_probe": startup_probe_payload(),
    }


def wait_until_visible(fetch, label):
    deadline = time.monotonic() + SETTLE_TIMEOUT
    while True:
        item = fetch()
        if item is not None:
            return item
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{label} remains reserved/unavailable after {SETTLE_TIMEOUT}s")
        print(f"Waiting for {label} to become visible...")
        time.sleep(SETTLE_POLL_SECONDS)


def ensure_queue():
    existing = get_queue()
    if existing is not None:
        print(f"Queue already exists: {QUEUE_NAME}")
        return existing
    print(f"Creating missing Queue: {QUEUE_NAME}")
    try:
        request("POST", f"{project_path()}/queues", queue_payload())
    except RuntimeError as exc:
        if "name_conflict" not in str(exc):
            raise
        print("Queue name is reserved; waiting for the existing Queue...")
    return wait_until_visible(get_queue, QUEUE_NAME)


def ensure_group(gpu_id):
    existing = get_group()
    if existing is not None:
        print(f"Container Group already exists: {GROUP_NAME}")
        return existing
    print(f"Creating missing Container Group: {GROUP_NAME}")
    try:
        request("POST", f"{project_path()}/containers", group_payload(gpu_id))
    except RuntimeError as exc:
        if "name_conflict" not in str(exc):
            raise
        print("Container Group name is reserved; waiting for the existing group...")
    return wait_until_visible(get_group, GROUP_NAME)


def wait_for_settle():
    deadline = time.monotonic() + SETTLE_TIMEOUT
    while True:
        group = wait_until_visible(get_group, GROUP_NAME)
        if not group.get("pending_change", False):
            return group
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{GROUP_NAME} still has a pending change")
        print(f"Waiting for {GROUP_NAME} pending change to settle...")
        time.sleep(SETTLE_POLL_SECONDS)


def assert_queue_connection(group):
    expected = {"path": "/prompt", "port": 3000, "queue_name": QUEUE_NAME}
    actual = group.get("queue_connection") or {}
    for key, value in expected.items():
        if actual.get(key) != value:
            raise RuntimeError(
                f"Existing group has incompatible queue_connection ({key}); "
                "do not change it implicitly. Stop/delete that group manually "
                "after preserving any jobs, then re-run --apply."
            )


def contains_expected(actual, expected):
    """Compare desired fields, ignoring extra read-only fields in Salad responses."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            k in actual and contains_expected(actual[k], v) for k, v in expected.items()
        )
    return actual == expected


def config_drift(group, gpu_id):
    drift = []
    container = group.get("container") or {}
    resource = container.get("resources") or {}
    if container.get("image") != IMAGE:
        drift.append("image")
    priority = group.get("priority", container.get("priority"))
    if priority != PRIORITY:
        drift.append("priority")
    expected_res = {**RESOURCE_SPEC, "gpu_classes": [gpu_id]}
    for key, expected in expected_res.items():
        actual = resource.get(key)
        if key == "gpu_classes":
            if set(actual or []) != set(expected):
                drift.append("resources.gpu_classes")
        elif actual is None or int(actual) != expected:
            drift.append(f"resources.{key}")
    # Do not print env values, which contain private R2 credentials.
    if container.get("environment_variables") != environment_payload():
        drift.append("environment_variables")
    if any((group.get("queue_autoscaler") or {}).get(k) != v for k, v in autoscaler_payload().items()):
        drift.append("queue_autoscaler")
    if not contains_expected(group.get("readiness_probe"), readiness_probe_payload()):
        drift.append("readiness_probe")
    if not contains_expected(group.get("startup_probe"), startup_probe_payload()):
        drift.append("startup_probe")
    return drift


def patch_group(gpu_id):
    # queue_connection is intentionally NOT patched (API support varies).
    desired = {
        "container": {
            "image": IMAGE,
            "priority": PRIORITY,
            "resources": {**RESOURCE_SPEC, "gpu_classes": [gpu_id]},
            "environment_variables": environment_payload(),
        },
        "queue_autoscaler": autoscaler_payload(),
        "readiness_probe": readiness_probe_payload(),
        "startup_probe": startup_probe_payload(),
    }
    deadline = time.monotonic() + SETTLE_TIMEOUT
    while True:
        try:
            request("PATCH", group_path(), desired, content_type="application/merge-patch+json")
            print("Existing Medium Container Group configuration PATCH accepted.")
            return
        except RuntimeError as exc:
            if "pending_update_in_progress" not in str(exc) or time.monotonic() >= deadline:
                raise
            print("Previous Salad update still pending; retrying...")
            time.sleep(SETTLE_POLL_SECONDS)


def report(gpu_id, apply):
    queue = get_queue()
    group = get_group()
    print(f"Organization/Project: {ORG}/{PROJECT}")
    print(f"Queue: {QUEUE_NAME} ({'FOUND' if queue else 'MISSING'})")
    print(f"Container Group: {GROUP_NAME} ({'FOUND' if group else 'MISSING'})")
    print(f"GPU: {GPU_NAME}; CPU: 4; RAM: 30 GB; SHM: 2048 MB; Disk: 100 GB")
    print("Priority: Medium; initial/min/max replicas: 0/0/1")
    print(f"Image: {IMAGE}")
    if group:
        assert_queue_connection(group)
        drift = config_drift(group, gpu_id)
        print("Configuration drift:", ", ".join(drift) if drift else "none")
        if (group.get("replicas") or 0) > 0:
            print("WARNING: Existing group has running/requested replicas; stop it manually if idle.")
    else:
        drift = []
    if not apply:
        print("READ-ONLY CHECK. Re-run with --apply to create/repair the Medium resources.")
        print("NOTE: Other Container Groups are not deleted by this script.")
        return

    ensure_queue()
    group = ensure_group(gpu_id)
    group = wait_for_settle()
    assert_queue_connection(group)
    drift = config_drift(group, gpu_id)
    if drift:
        print("Repairing existing group fields:", ", ".join(drift))
        patch_group(gpu_id)
        group = wait_for_settle()
    assert_queue_connection(group)
    remaining = config_drift(group, gpu_id)
    if remaining:
        raise RuntimeError("Post-deploy config mismatch: " + ", ".join(remaining))
    if get_queue() is None:
        raise RuntimeError("Queue missing after deployment")
    print("SUCCESS: target Medium Queue/Group verified; no duplicate created.")
    print("Other groups/queues are left untouched; remove obsolete ones manually.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create/repair Medium Queue and Group")
    parser.add_argument("--priority", choices=(PRIORITY,), default=PRIORITY,
                        help="Backward-compatible option; only medium is supported")
    args = parser.parse_args()
    validate_configuration()
    gpu_id = select_gpu()
    report(gpu_id, args.apply)


if __name__ == "__main__":
    main()
