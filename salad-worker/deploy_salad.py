#!/usr/bin/env python3
"""Create/validate Salad Job Queue + GPU Container Group.
Default is dry-run. Use --apply to create missing resources.
"""
import argparse
import json
import os
import urllib.error
import urllib.request

BASE = "https://api.salad.com/api/public"
USER_AGENT = "comfyui-controller/1.0"


def env(name, default=None, required=False):
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing {name}")
    return value


API_KEY = env("SALAD_API_KEY", required=True)
ORG = env("SALAD_ORG", "imanprojects")
PROJECT = env("SALAD_PROJECT", "comfy")
QUEUE = env("SALAD_QUEUE", "qwen-comfyui")
GROUP = env("SALAD_CONTAINER_GROUP", "qwen-comfyui-fp8")
IMAGE = env("SALAD_IMAGE", "ghcr.io/imannasresfahani/comfyui-controller-salad-worker:fp8")


def request(method, path, body=None, allow_404=False):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Salad-Api-Key": API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        if allow_404 and exc.code == 404:
            return None
        raise RuntimeError(f"{method} {url} -> {exc.code}: {raw}") from exc


def normalize_gpu_name(value):
    return " ".join(str(value).strip().lower().split())


def gpu_classes():
    data = request("GET", f"/organizations/{ORG}/gpu-classes")
    items = data.get("items", data if isinstance(data, list) else [])
    requested = env("SALAD_GPU_NAMES", "RTX 4090 (24 GB),RTX 5090 (32 GB)")
    wanted = [normalize_gpu_name(x) for x in requested.split(",") if x.strip()]
    available_by_name = {
        normalize_gpu_name(item.get("name", "")): item for item in items
    }
    matches, missing = [], []
    for wanted_name in wanted:
        item = available_by_name.get(wanted_name)
        if item is None:
            missing.append(wanted_name)
        else:
            matches.append({"id": item["id"], "name": item["name"]})
    if missing:
        available = [item.get("name") for item in items]
        raise SystemExit(
            "Requested GPU classes were not found by exact name. "
            f"Missing={missing!r}\nAvailable sample={available[:50]!r}"
        )
    if not matches:
        raise SystemExit("No GPU classes selected.")
    return matches


def queue_exists():
    return request("GET", f"/organizations/{ORG}/projects/{PROJECT}/queues/{QUEUE}", allow_404=True)


def group_exists():
    return request("GET", f"/organizations/{ORG}/projects/{PROJECT}/containers/{GROUP}", allow_404=True)


def queue_payload():
    return {"name": QUEUE, "display_name": "Qwen ComfyUI Jobs"}


def group_payload(gpus):
    environment_variables = {
        "MANIFEST": "/opt/qvr-salad/manifest.yaml",
        "PORT": "3000",
        "LRU_CACHE_SIZE_GB": "40",
        "SALAD_LOG_LEVEL": "info",
        "AWS_ACCESS_KEY_ID": env("R2_ACCESS_KEY_ID", required=True),
        "AWS_SECRET_ACCESS_KEY": env("R2_SECRET_ACCESS_KEY", required=True),
        "AWS_REGION": env("R2_REGION", "auto"),
        "AWS_ENDPOINT_URL_S3": env("R2_ENDPOINT_URL", required=True),
        "AWS_ENDPOINT_URL": env("R2_ENDPOINT_URL", required=True),
    }
    hf_token = env("HF_TOKEN", "")
    if hf_token:
        environment_variables["HF_TOKEN"] = hf_token

    return {
        "name": GROUP,
        "display_name": "Qwen ComfyUI Scale-to-Zero",
        "container": {
            "image": IMAGE,
            "resources": {
                "cpu": 4,
                "memory": 16384,
                "shm_size": 2048,
                "storage_amount": 53687091200,
                "gpu_classes": [gpu["id"] for gpu in gpus],
            },
            "environment_variables": environment_variables,
            "priority": env("SALAD_PRIORITY", "batch"),
        },
        "replicas": int(env("SALAD_INITIAL_REPLICAS", "0")),
        "restart_policy": "always",
        "autostart_policy": True,
        "networking": {"protocol": "http", "port": 3000, "auth": True},
        "queue_connection": {"path": "/prompt", "port": 3000, "queue_name": QUEUE},
        "queue_autoscaler": {
            "min_replicas": int(env("SALAD_MIN_REPLICAS", "0")),
            "max_replicas": int(env("SALAD_MAX_REPLICAS", "1")),
            "desired_queue_length": int(env("SALAD_DESIRED_QUEUE_LENGTH", "1")),
            "polling_period": int(env("SALAD_POLLING_PERIOD", "30")),
            "max_upscale_per_minute": 1,
            "max_downscale_per_minute": 1,
        },
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


def redacted(payload):
    copied = json.loads(json.dumps(payload))
    values = copied.get("container", {}).get("environment_variables", {})
    for key in ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "HF_TOKEN"]:
        if key in values and values[key]:
            values[key] = "***REDACTED***"
    return copied


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually create missing Salad resources")
    args = parser.parse_args()

    print(f"Organization: {ORG}")
    print(f"Project: {PROJECT}")
    print(f"Queue: {QUEUE}")
    print(f"Container group: {GROUP}")
    print(f"Image: {IMAGE}")

    gpus = gpu_classes()
    print("\nMatched GPU classes:")
    print(json.dumps(gpus, indent=2))

    queue_config = queue_payload()
    group_config = group_payload(gpus)

    print("\nQueue payload:")
    print(json.dumps(queue_config, indent=2))

    print("\nContainer group payload:")
    print(json.dumps(redacted(group_config), indent=2))

    if not args.apply:
        print("\nDRY RUN ONLY. Re-run with --apply to create missing resources.")
        return

    queue = queue_exists()
    if queue is None:
        print("\nCreating queue...")
        queue = request(
            "POST",
            f"/organizations/{ORG}/projects/{PROJECT}/queues",
            queue_config,
        )
        print("Queue created:", json.dumps(queue, indent=2))
    else:
        print("\nQueue already exists; leaving it unchanged.")

    group = group_exists()
    if group is None:
        print("\nCreating container group...")
        group = request(
            "POST",
            f"/organizations/{ORG}/projects/{PROJECT}/containers",
            group_config,
        )
        print("Container group created:", json.dumps(group, indent=2))
    else:
        print("\nContainer group already exists; leaving it unchanged.")
        print("This script intentionally does not PATCH an existing production group.")


if __name__ == "__main__":
    main()
