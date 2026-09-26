#!/usr/bin/env python3
"""
Creates/validates the Salad Job Queue + GPU Container Group.

Default mode is dry-run. Use --apply to mutate Salad resources.
No GitHub writes are performed.
"""
import os
import sys
import json
import argparse
import urllib.request
import urllib.error

BASE = "https://api.salad.com/api/public"

def env(name, default=None, required=False):
    v = os.getenv(name, default)
    if required and not v:
        raise SystemExit(f"Missing {name}")
    return v

API_KEY = env("SALAD_API_KEY", required=True)
ORG = env("SALAD_ORG", required=True)
PROJECT = env("SALAD_PROJECT", required=True)
QUEUE = env("SALAD_QUEUE", "qwen-comfyui")
GROUP = env("SALAD_CONTAINER_GROUP", "qwen-comfyui-fp8")
IMAGE = env("SALAD_IMAGE", required=True)

def request(method, path, body=None, allow_404=False):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Salad-Api-Key": API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        if allow_404 and e.code == 404:
            return None
        raise RuntimeError(f"{method} {url} -> {e.code}: {raw}") from e

def gpu_classes():
    data = request("GET", f"/organizations/{ORG}/gpu-classes")
    items = data.get("items", data if isinstance(data, list) else [])
    wanted = [x.strip().lower() for x in env("SALAD_GPU_NAMES", "RTX 4090,RTX 5090").split(",") if x.strip()]
    matches = []
    for item in items:
        name = str(item.get("name", ""))
        if any(w in name.lower() for w in wanted):
            matches.append({"id": item["id"], "name": name})
    if not matches:
        names = [x.get("name") for x in items]
        raise SystemExit(
            "No requested GPU classes found. Requested="
            + repr(wanted)
            + "\nAvailable sample="
            + repr(names[:30])
        )
    return matches

def queue_exists():
    return request(
        "GET",
        f"/organizations/{ORG}/projects/{PROJECT}/queues/{QUEUE}",
        allow_404=True,
    )

def group_exists():
    return request(
        "GET",
        f"/organizations/{ORG}/projects/{PROJECT}/containers/{GROUP}",
        allow_404=True,
    )

def queue_payload():
    return {
        "name": QUEUE,
        "display_name": "Qwen ComfyUI Jobs",
    }

def group_payload(gpus):
    envs = {
        "MANIFEST": "/opt/qvr-salad/manifest.yaml",
        "PORT": "3000",
        "LRU_CACHE_SIZE_GB": "40",
        "SALAD_LOG_LEVEL": "info",
        "AWS_ACCESS_KEY_ID": env("R2_ACCESS_KEY_ID", required=True),
        "AWS_SECRET_ACCESS_KEY": env("R2_SECRET_ACCESS_KEY", required=True),
        "AWS_REGION": env("R2_REGION", "auto"),
        # AWS SDK shared endpoint configuration; R2 is S3-compatible.
        "AWS_ENDPOINT_URL_S3": env("R2_ENDPOINT_URL", required=True),
        # Also set the global endpoint for SDK versions that only consume the common setting.
        "AWS_ENDPOINT_URL": env("R2_ENDPOINT_URL", required=True),
    }
    hf = env("HF_TOKEN", "")
    if hf:
        envs["HF_TOKEN"] = hf

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
                "gpu_classes": [g["id"] for g in gpus],
            },
            "environment_variables": envs,
            "priority": env("SALAD_PRIORITY", "lowest"),
        },
        "replicas": 0,
        "restart_policy": "always",
        "autostart_policy": True,
        "networking": {
            "protocol": "http",
            "port": 3000,
            "auth": True,
        },
        "queue_connection": {
            "path": "/prompt",
            "port": 3000,
            "queue_name": QUEUE,
        },
        "queue_autoscaler": {
            "min_replicas": int(env("SALAD_MIN_REPLICAS", "0")),
            "max_replicas": int(env("SALAD_MAX_REPLICAS", "1")),
            "desired_queue_length": int(env("SALAD_DESIRED_QUEUE_LENGTH", "1")),
            "polling_period": int(env("SALAD_POLLING_PERIOD", "30")),
            "max_upscale_per_minute": 1,
            "max_downscale_per_minute": 1,
        },
        "readiness_probe": {
            "http": {"path": "/ready", "port": 3000},
            "initial_delay_seconds": 10,
            "period_seconds": 10,
            "timeout_seconds": 5,
            "success_threshold": 1,
            "failure_threshold": 20,
        },
        "startup_probe": {
            "http": {"path": "/health", "port": 3000},
            "initial_delay_seconds": 120,
            "period_seconds": 30,
            "timeout_seconds": 5,
            "success_threshold": 1,
            "failure_threshold": 20,
        },
    }

def redacted(payload):
    copy = json.loads(json.dumps(payload))
    ev = copy.get("container", {}).get("environment_variables", {})
    for k in ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "HF_TOKEN"]:
        if k in ev and ev[k]:
            ev[k] = "***REDACTED***"
    return copy

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually create resources")
    args = ap.parse_args()

    gpus = gpu_classes()
    print("Matched GPU classes:")
    print(json.dumps(gpus, indent=2))

    qp = queue_payload()
    gp = group_payload(gpus)

    print("\nQueue payload:")
    print(json.dumps(qp, indent=2))
    print("\nContainer group payload:")
    print(json.dumps(redacted(gp), indent=2))

    if not args.apply:
        print("\nDRY RUN ONLY. Re-run with --apply to create missing resources.")
        return

    q = queue_exists()
    if q is None:
        print("\nCreating queue...")
        q = request(
            "POST",
            f"/organizations/{ORG}/projects/{PROJECT}/queues",
            qp,
        )
        print("Queue created:", json.dumps(q, indent=2))
    else:
        print("\nQueue already exists; leaving it unchanged.")

    g = group_exists()
    if g is None:
        print("\nCreating container group...")
        g = request(
            "POST",
            f"/organizations/{ORG}/projects/{PROJECT}/containers",
            gp,
        )
        print("Container group created:", json.dumps(g, indent=2))
    else:
        print("\nContainer group already exists; leaving it unchanged.")
        print("This script intentionally does not PATCH an existing production group.")

if __name__ == "__main__":
    main()
