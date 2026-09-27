#!/usr/bin/env python3
import argparse
import json
import os
import time
import urllib.error
import urllib.request

BASE = "https://api.salad.com/api/public"
USER_AGENT = "comfyui-controller/1.3"
PRIORITIES = ("high", "medium", "low", "batch")

SENSITIVE_KEYS = {
    "aws_access_key_id",
    "aws_secret_access_key",
    "hf_token",
    "salad_api_key",
    "r2_access_key_id",
    "r2_secret_access_key",
}


def env(name, default=None, required=False):
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing {name}")
    return value


API_KEY = env("SALAD_API_KEY", required=True)
ORG = env("SALAD_ORG", "imanprojects")
PROJECT = env("SALAD_PROJECT", "comfy")
QUEUE_PREFIX = env("SALAD_QUEUE_PREFIX", "qwen-comfyui")
GROUP_PREFIX = env("SALAD_CONTAINER_GROUP_PREFIX", "qwen-comfyui-fp8")
IMAGE = env(
    "SALAD_IMAGE",
    "ghcr.io/imannasresfahani/comfyui-controller-salad-worker:fp8",
)

SETTLE_TIMEOUT = int(env("SALAD_CONFIG_SETTLE_TIMEOUT", "300"))
SETTLE_POLL_SECONDS = int(env("SALAD_CONFIG_SETTLE_POLL_SECONDS", "5"))


def request(
    method,
    path,
    body=None,
    allow_404=False,
    content_type="application/json",
):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None

    req = urllib.request.Request(
        url,
        data=data,
        method=method,
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

        raise RuntimeError(
            f"{method} {url} -> {exc.code}: {raw}"
        ) from exc


def redact_secrets(value):
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS and item:
                output[key] = "***REDACTED***"
            else:
                output[key] = redact_secrets(item)
        return output

    if isinstance(value, list):
        return [redact_secrets(item) for item in value]

    return value


def normalize_gpu_name(value):
    return " ".join(str(value).strip().lower().split())


def gpu_classes():
    data = request(
        "GET",
        f"/organizations/{ORG}/gpu-classes",
    )
    items = data.get(
        "items",
        data if isinstance(data, list) else [],
    )

    requested = env(
        "SALAD_GPU_NAMES",
        "RTX 4090 (24 GB),RTX 5090 (32 GB)",
    )

    wanted = [
        normalize_gpu_name(item)
        for item in requested.split(",")
        if item.strip()
    ]

    available_by_name = {
        normalize_gpu_name(item.get("name", "")): item
        for item in items
    }

    matches = []
    missing = []

    for wanted_name in wanted:
        item = available_by_name.get(wanted_name)
        if item is None:
            missing.append(wanted_name)
        else:
            matches.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                }
            )

    if missing:
        raise SystemExit(
            f"Requested GPU classes were not found: {missing!r}"
        )

    if not matches:
        raise SystemExit("No GPU classes selected.")

    return matches


def queue_name(priority):
    return f"{QUEUE_PREFIX}-{priority}"


def group_name(priority):
    return f"{GROUP_PREFIX}-{priority}"


def queue_path(priority):
    return (
        f"/organizations/{ORG}"
        f"/projects/{PROJECT}"
        f"/queues/{queue_name(priority)}"
    )


def group_path(priority):
    return (
        f"/organizations/{ORG}"
        f"/projects/{PROJECT}"
        f"/containers/{group_name(priority)}"
    )


def queue_exists(priority):
    return request(
        "GET",
        queue_path(priority),
        allow_404=True,
    )


def group_exists(priority):
    return request(
        "GET",
        group_path(priority),
        allow_404=True,
    )


def queue_payload(priority):
    label = (
        "Batch / Lowest"
        if priority == "batch"
        else priority.title()
    )

    return {
        "name": queue_name(priority),
        "display_name": f"Qwen ComfyUI {label} Jobs",
    }


def autoscaler_payload():
    return {
        "min_replicas": int(
            env("SALAD_MIN_REPLICAS", "0")
        ),
        "max_replicas": int(
            env("SALAD_MAX_REPLICAS", "1")
        ),
        "desired_queue_length": int(
            env("SALAD_DESIRED_QUEUE_LENGTH", "1")
        ),
        "polling_period": int(
            env("SALAD_POLLING_PERIOD", "30")
        ),
        "max_upscale_per_minute": 1,
        "max_downscale_per_minute": 1,
    }


def environment_payload():
    values = {
        "MANIFEST": "/opt/qvr-salad/manifest.yaml",
        "PORT": "3000",
        "LRU_CACHE_SIZE_GB": "40",
        "SALAD_LOG_LEVEL": "info",
        "AWS_ACCESS_KEY_ID": env(
            "R2_ACCESS_KEY_ID",
            required=True,
        ),
        "AWS_SECRET_ACCESS_KEY": env(
            "R2_SECRET_ACCESS_KEY",
            required=True,
        ),
        "AWS_REGION": env(
            "R2_REGION",
            "auto",
        ),
        "AWS_ENDPOINT_URL_S3": env(
            "R2_ENDPOINT_URL",
            required=True,
        ),
        "AWS_ENDPOINT_URL": env(
            "R2_ENDPOINT_URL",
            required=True,
        ),
    }

    hf_token = env("HF_TOKEN", "")
    if hf_token:
        values["HF_TOKEN"] = hf_token

    return values


def group_payload(gpus, priority):
    label = (
        "Batch / Lowest"
        if priority == "batch"
        else priority.title()
    )

    return {
        "name": group_name(priority),
        "display_name": f"Qwen ComfyUI {label}",
        "container": {
            "image": IMAGE,
            "resources": {
                "cpu": 4,
                "memory": 16384,
                "shm_size": 2048,
                "storage_amount": 53687091200,
                "gpu_classes": [
                    gpu["id"]
                    for gpu in gpus
                ],
            },
            "environment_variables": environment_payload(),
            "priority": priority,
        },
        "replicas": int(
            env("SALAD_INITIAL_REPLICAS", "0")
        ),
        "restart_policy": "always",
        "autostart_policy": True,
        "queue_connection": {
            "path": "/prompt",
            "port": 3000,
            "queue_name": queue_name(priority),
        },
        "queue_autoscaler": autoscaler_payload(),
        "readiness_probe": {
            "http": {
                "path": "/ready",
                "port": 3000,
                "scheme": "http",
                "headers": [],
            },
            "initial_delay_seconds": 10,
            "period_seconds": 10,
            "timeout_seconds": 5,
            "success_threshold": 1,
            "failure_threshold": 20,
        },
        "startup_probe": {
            "http": {
                "path": "/health",
                "port": 3000,
                "scheme": "http",
                "headers": [],
            },
            "initial_delay_seconds": 120,
            "period_seconds": 30,
            "timeout_seconds": 5,
            "success_threshold": 1,
            "failure_threshold": 20,
        },
    }


def wait_for_group_settle(priority, phase):
    """
    Salad rejects PATCH while a previous create/update is still pending.
    Wait until the group reports pending_change == False.
    """
    deadline = time.monotonic() + SETTLE_TIMEOUT
    attempt = 0

    while True:
        attempt += 1
        group = group_exists(priority)

        if group is None:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"{group_name(priority)} did not become readable "
                    f"within {SETTLE_TIMEOUT}s during {phase}."
                )

            print(
                f"Waiting for {group_name(priority)} "
                f"to become readable..."
            )
            time.sleep(SETTLE_POLL_SECONDS)
            continue

        pending = bool(group.get("pending_change", False))
        state = group.get("current_state") or {}
        status = state.get("status")

        print(
            f"Settle {priority} [{phase}] #{attempt}: "
            f"pending_change={pending}, "
            f"status={status!r}, "
            f"version={group.get('version')}"
        )

        if not pending:
            return group

        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"{group_name(priority)} still has pending_change=true "
                f"after {SETTLE_TIMEOUT}s during {phase}."
            )

        time.sleep(SETTLE_POLL_SECONDS)


def sync_autoscaler(priority):
    desired = autoscaler_payload()
    deadline = time.monotonic() + SETTLE_TIMEOUT
    attempt = 0

    while True:
        attempt += 1

        try:
            result = request(
                "PATCH",
                group_path(priority),
                {"queue_autoscaler": desired},
                content_type="application/merge-patch+json",
            )

            returned = result.get("queue_autoscaler")

            print(
                f"Autoscaler PATCH {priority}: "
                f"{'OK' if returned else 'accepted'}"
            )

            return result

        except RuntimeError as exc:
            message = str(exc)

            if (
                "pending_update_in_progress" not in message
                or time.monotonic() >= deadline
            ):
                raise

            print(
                f"Autoscaler PATCH {priority}: "
                f"previous update still pending; retrying "
                f"in {SETTLE_POLL_SECONDS}s..."
            )

            time.sleep(SETTLE_POLL_SECONDS)


def verify_group(priority):
    group = group_exists(priority)

    if group is None:
        raise RuntimeError(
            f"{group_name(priority)} not found after deployment."
        )

    actual_priority = group.get("priority")
    connection = group.get("queue_connection")
    autoscaler = group.get("queue_autoscaler")

    print(
        f"Verify {priority}: "
        f"priority={actual_priority!r}, "
        f"queue_connection={'YES' if connection else 'NO'}, "
        f"queue_autoscaler={'YES' if autoscaler else 'NO'}"
    )

    if actual_priority != priority:
        raise RuntimeError(
            f"{group_name(priority)} priority mismatch: "
            f"{actual_priority!r}"
        )

    if not connection:
        raise RuntimeError(
            f"{group_name(priority)} has no queue_connection."
        )

    if not autoscaler:
        raise RuntimeError(
            f"{group_name(priority)} has no queue_autoscaler "
            "even after PATCH."
        )

    desired = autoscaler_payload()

    for key, expected in desired.items():
        actual = autoscaler.get(key)
        if actual != expected:
            raise RuntimeError(
                f"{group_name(priority)} autoscaler mismatch "
                f"for {key}: expected {expected!r}, got {actual!r}"
            )

    return group


def create_or_check(gpus, priority, apply):
    qp = queue_payload(priority)
    gp = group_payload(gpus, priority)

    print(f"\n=== {priority.upper()} ===")
    print("Queue:", queue_name(priority))
    print("Container group:", group_name(priority))

    if not apply:
        print("Queue payload:")
        print(
            json.dumps(
                redact_secrets(qp),
                indent=2,
            )
        )

        print("Container group payload:")
        print(
            json.dumps(
                redact_secrets(gp),
                indent=2,
            )
        )

        print(
            "Apply behavior: create missing resources, "
            "wait for Salad to settle, PATCH queue_autoscaler, "
            "wait again, then verify."
        )
        return

    if queue_exists(priority) is None:
        print("Creating queue...")
        request(
            "POST",
            (
                f"/organizations/{ORG}"
                f"/projects/{PROJECT}"
                f"/queues"
            ),
            qp,
        )
    else:
        print("Queue already exists.")

    if group_exists(priority) is None:
        print("Creating container group...")
        request(
            "POST",
            (
                f"/organizations/{ORG}"
                f"/projects/{PROJECT}"
                f"/containers"
            ),
            gp,
        )
    else:
        print("Container group already exists.")

    # A newly created/updated Salad group may temporarily reject PATCH with
    # pending_update_in_progress. Wait until that operation has settled.
    wait_for_group_settle(priority, "before autoscaler PATCH")

    sync_autoscaler(priority)

    # The PATCH itself can create another pending configuration change.
    wait_for_group_settle(priority, "after autoscaler PATCH")

    verify_group(priority)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create missing resources and sync autoscaling",
    )

    parser.add_argument(
        "--priority",
        choices=PRIORITIES,
        help="Deploy/check only one priority. Default: all four.",
    )

    args = parser.parse_args()

    selected = (
        (args.priority,)
        if args.priority
        else PRIORITIES
    )

    print(f"Organization: {ORG}")
    print(f"Project: {PROJECT}")
    print(f"Image: {IMAGE}")
    print("Priorities:", ", ".join(selected))

    gpus = gpu_classes()

    print("\nMatched GPU classes:")
    print(json.dumps(gpus, indent=2))

    for priority in selected:
        create_or_check(
            gpus,
            priority,
            args.apply,
        )

    if not args.apply:
        print("\nDRY RUN ONLY. Re-run with --apply.")


if __name__ == "__main__":
    main()
