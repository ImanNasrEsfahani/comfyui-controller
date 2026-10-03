#!/usr/bin/env python3
"""Idempotent deployment of ONE Salad Queue and ONE GPU Container Group.

Every configurable deployment value is required from the root .env.
Default run is read-only; --apply creates/reconciles ONLY the named resources.
Use --apply --bootstrap to request an initial replica explicitly, including
for an existing scale-to-zero group. Plain --apply never wakes an idle group.
Never deletes old resources, auto-renames groups, or changes the Queue name.
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required .env setting: {name}")
    return value


def integer(name, minimum=None):
    value = required(name)
    try:
        number = int(value)
    except ValueError:
        raise SystemExit(f"{name} must be an integer, got {value!r}") from None
    if minimum is not None and number < minimum:
        raise SystemExit(f"{name} must be at least {minimum}, got {number}")
    return number


def boolean(name):
    value = required(name).lower()
    if value not in ("true", "false"):
        raise SystemExit(f"{name} must be true or false")
    return value == "true"


BASE = required("SALAD_API_BASE_URL").rstrip("/")
USER_AGENT = required("SALAD_USER_AGENT")
API_KEY = required("SALAD_API_KEY")
ORG = required("SALAD_ORG")
PROJECT = required("SALAD_PROJECT")
QUEUE_NAME = required("SALAD_QUEUE_NAME")
QUEUE_DISPLAY_NAME = required("SALAD_QUEUE_DISPLAY_NAME")
GROUP_NAME = required("SALAD_CONTAINER_GROUP_NAME")
GROUP_DISPLAY_NAME = required("SALAD_CONTAINER_GROUP_DISPLAY_NAME")
PRIORITY = required("SALAD_PRIORITY").lower()
GPU_NAME = required("SALAD_GPU_NAME")
IMAGE = required("SALAD_IMAGE")
HTTP_TIMEOUT = integer("SALAD_HTTP_TIMEOUT_SECONDS", 1)
SETTLE_TIMEOUT = integer("SALAD_CONFIG_SETTLE_TIMEOUT", 1)
SETTLE_POLL_SECONDS = integer("SALAD_CONFIG_SETTLE_POLL_SECONDS", 1)
RESOURCE_SPEC = {
    "cpu": integer("SALAD_CPU", 1),
    "memory": integer("SALAD_MEMORY_MB", 1),
    "shm_size": integer("SALAD_SHM_MB", 1),
    "storage_amount": integer("SALAD_STORAGE_GB", 1) * 1024 ** 3,
}
INITIAL_REPLICAS = integer("SALAD_INITIAL_REPLICAS", 0)
BOOTSTRAP_REPLICAS = integer("SALAD_BOOTSTRAP_REPLICAS", 1)
MIN_REPLICAS = integer("SALAD_MIN_REPLICAS", 0)
MAX_REPLICAS = integer("SALAD_MAX_REPLICAS", 1)
RESTART_POLICY = required("SALAD_RESTART_POLICY")
AUTOSTART_POLICY = boolean("SALAD_AUTOSTART_POLICY")
QUEUE_CONNECTION_PATH = required("SALAD_QUEUE_CONNECTION_PATH")
WORKER_PORT = integer("SALAD_WORKER_PORT", 1)
WORKER_SCHEME = required("SALAD_WORKER_SCHEME")


def validate_configuration():
    if PRIORITY not in ("high", "medium", "low", "batch"):
        raise SystemExit("SALAD_PRIORITY must be a Salad priority: high, medium, low, batch")
    if INITIAL_REPLICAS != 0 or MIN_REPLICAS != 0 or MAX_REPLICAS != 1:
        raise SystemExit("Single-group, scale-to-zero deployment requires initial/min/max: 0 / 0 / 1")
    if BOOTSTRAP_REPLICAS != 1:
        raise SystemExit("Single-GPU bootstrap requires SALAD_BOOTSTRAP_REPLICAS=1")
    if not (BASE.startswith("https://") or BASE.startswith("http://")):
        raise SystemExit("SALAD_API_BASE_URL must be an HTTP(S) URL")


def request(method, path, body=None, *, allow_404=False, content_type="application/json"):
    data = json.dumps(body).encode() if body is not None else None
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
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        if allow_404 and exc.code == 404:
            return None
        # Salad's name_conflict is needed by the retry loop; never include env secrets.
        raise RuntimeError(f"{method} {url} -> HTTP {exc.code}: {raw}") from exc


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
    result = request("GET", f"/organizations/{ORG}/gpu-classes")
    items = result if isinstance(result, list) else result.get("items", [])
    normalize = lambda value: " ".join(str(value).strip().lower().split())
    matches = [item for item in items if normalize(item.get("name")) == normalize(GPU_NAME)]
    if len(matches) != 1:
        raise RuntimeError(f"GPU class {GPU_NAME!r}: expected one result; found {len(matches)}")
    return matches[0]["id"]


def autoscaler_payload():
    return {
        "min_replicas": MIN_REPLICAS,
        "max_replicas": MAX_REPLICAS,
        "desired_queue_length": integer("SALAD_DESIRED_QUEUE_LENGTH", 1),
        "polling_period": integer("SALAD_POLLING_PERIOD", 1),
        "max_upscale_per_minute": integer("SALAD_MAX_UPSCALE_PER_MINUTE", 1),
        "max_downscale_per_minute": integer("SALAD_MAX_DOWNSCALE_PER_MINUTE", 1),
    }


def probe_payload(prefix, path_key):
    return {
        "http": {
            "path": required(path_key),
            "port": WORKER_PORT,
            "scheme": WORKER_SCHEME,
            "headers": [],
        },
        "initial_delay_seconds": integer(prefix + "_INITIAL_DELAY_SECONDS", 0),
        "period_seconds": integer(prefix + "_PERIOD_SECONDS", 1),
        "timeout_seconds": integer(prefix + "_TIMEOUT_SECONDS", 1),
        "success_threshold": integer(prefix + "_SUCCESS_THRESHOLD", 1),
        "failure_threshold": integer(prefix + "_FAILURE_THRESHOLD", 1),
    }


def readiness_probe_payload():
    return probe_payload("SALAD_READINESS", "SALAD_READINESS_PATH")


def startup_probe_payload():
    return probe_payload("SALAD_STARTUP", "SALAD_STARTUP_PATH")


def environment_payload():
    values = {
        "MANIFEST": required("SALAD_MANIFEST_PATH"),
        "PORT": str(WORKER_PORT),
        "LRU_CACHE_SIZE_GB": str(integer("SALAD_LRU_CACHE_SIZE_GB", 0)),
        "SALAD_LOG_LEVEL": required("SALAD_LOG_LEVEL"),
        "READY_TIMEOUT_SECONDS": str(integer("SALAD_READY_TIMEOUT_SECONDS", 1)),
        "STARTUP_CHECK_MAX_TRIES": str(integer("SALAD_STARTUP_CHECK_MAX_TRIES", 1)),
        "STARTUP_CHECK_INTERVAL_S": str(integer("SALAD_STARTUP_CHECK_INTERVAL_S", 1)),
        "AWS_ACCESS_KEY_ID": required("R2_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": required("R2_SECRET_ACCESS_KEY"),
        "AWS_REGION": required("R2_REGION"),
        "AWS_ENDPOINT_URL_S3": required("R2_ENDPOINT_URL"),
        "AWS_ENDPOINT_URL": required("R2_ENDPOINT_URL"),
    }
    token = os.environ.get("HF_TOKEN", "").strip()
    if token:
        values["HF_TOKEN"] = token
    return values


def queue_payload():
    return {"name": QUEUE_NAME, "display_name": QUEUE_DISPLAY_NAME}


def group_payload(gpu_id, replicas=None):
    if replicas is None:
        replicas = INITIAL_REPLICAS
    return {
        "name": GROUP_NAME,
        "display_name": GROUP_DISPLAY_NAME,
        "container": {
            "image": IMAGE,
            "resources": {**RESOURCE_SPEC, "gpu_classes": [gpu_id]},
            "environment_variables": environment_payload(),
            "priority": PRIORITY,
        },
        "replicas": replicas,
        "restart_policy": RESTART_POLICY,
        "autostart_policy": AUTOSTART_POLICY,
        "queue_connection": {
            "path": QUEUE_CONNECTION_PATH,
            "port": WORKER_PORT,
            "queue_name": QUEUE_NAME,
        },
        "queue_autoscaler": autoscaler_payload(),
        "readiness_probe": readiness_probe_payload(),
        "startup_probe": startup_probe_payload(),
    }


def ensure_resource(kind, fetch, path, payload):
    """GET before each POST; retry if deletion keeps a name temporarily reserved."""
    deadline = time.monotonic() + SETTLE_TIMEOUT
    while True:
        existing = fetch()
        if existing is not None:
            print(f"{kind} already exists: {existing.get('name', path)}", flush=True)
            return existing
        print(f"Creating missing {kind}: {payload['name']}", flush=True)
        try:
            request("POST", path, payload)
        except RuntimeError as exc:
            if "name_conflict" not in str(exc):
                raise
            print(f"{kind} name reserved (GET=404, POST=name_conflict); retrying...", flush=True)
        # The control plane can accept POST before GET starts returning the object.
        existing = fetch()
        if existing is not None:
            return existing
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"{kind} {payload['name']!r} remained unavailable after {SETTLE_TIMEOUT}s. "
                "Check Salad's deletion state or change only its name in .env."
            )
        time.sleep(SETTLE_POLL_SECONDS)


def ensure_queue():
    return ensure_resource("Queue", get_queue, f"{project_path()}/queues", queue_payload())


def ensure_group(gpu_id, *, bootstrap=False):
    # For a missing group, an explicitly requested bootstrap starts at one.
    # For an existing group, ensure_resource does not touch the replica count.
    target = BOOTSTRAP_REPLICAS if bootstrap else INITIAL_REPLICAS
    return ensure_resource(
        "Container Group", get_group, f"{project_path()}/containers",
        group_payload(gpu_id, replicas=target),
    )


def wait_for_settle():
    deadline = time.monotonic() + SETTLE_TIMEOUT
    while True:
        group = get_group()
        if group is not None and not group.get("pending_change", False):
            return group
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{GROUP_NAME!r} is not readable/settled after {SETTLE_TIMEOUT}s")
        print(f"Waiting for {GROUP_NAME} to settle...", flush=True)
        time.sleep(SETTLE_POLL_SECONDS)


def assert_queue_connection(group):
    expected = group_payload("IGNORED")["queue_connection"]
    actual = group.get("queue_connection") or {}
    for key, value in expected.items():
        if actual.get(key) != value:
            raise RuntimeError(
                f"Existing group has incompatible queue_connection ({key}). "
                "Do not silently switch queues. Resolve in Salad before --apply."
            )


def contains_expected(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and contains_expected(actual[key], value)
            for key, value in expected.items()
        )
    return actual == expected


def config_drift(group, gpu_id):
    drift = []
    container = group.get("container") or {}
    actual_resources = container.get("resources") or {}
    if container.get("image") != IMAGE:
        drift.append("image")
    if group.get("priority", container.get("priority")) != PRIORITY:
        drift.append("priority")
    for key, value in {**RESOURCE_SPEC, "gpu_classes": [gpu_id]}.items():
        actual = actual_resources.get(key)
        if key == "gpu_classes":
            if set(actual or []) != set(value):
                drift.append("resources.gpu_classes")
        elif actual is None or int(actual) != value:
            drift.append(f"resources.{key}")
    actual_environment = container.get("environment_variables") or {}
    desired_environment = environment_payload()
    for key, value in desired_environment.items():
        actual = actual_environment.get(key)
        if key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "HF_TOKEN") and actual in (
            "***", "********", "***REDACTED***"
        ):
            continue
        if actual != value:
            drift.append("environment_variables")
            break
    for key, expected in (
        ("queue_autoscaler", autoscaler_payload()),
        ("readiness_probe", readiness_probe_payload()),
        ("startup_probe", startup_probe_payload()),
    ):
        if not contains_expected(group.get(key), expected):
            drift.append(key)
    return drift


def patch_group(gpu_id):
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
            print(f"PATCH accepted for {GROUP_NAME}", flush=True)
            return
        except RuntimeError as exc:
            if "pending_update_in_progress" not in str(exc) or time.monotonic() >= deadline:
                raise
            print("Previous Salad update still pending; retrying...", flush=True)
            time.sleep(SETTLE_POLL_SECONDS)


def bootstrap_group(group):
    """Explicit, idempotent initial scale-up. Never downscale an active worker.

    This is deliberately NOT run by plain --apply. A manual replica may incur
    Salad charges. It does not promise that the queue autoscaler can recover
    from zero in later runs; that behavior must be tested separately.
    """
    if group.get("pending_change"):
        raise RuntimeError("Group has a pending Salad change; bootstrap aborted")
    current = group.get("replicas") or 0
    if current > BOOTSTRAP_REPLICAS:
        raise RuntimeError("Existing replicas exceed bootstrap target; refusing to downscale")
    if current < BOOTSTRAP_REPLICAS:
        print(f"Bootstrapping {GROUP_NAME}: {current} -> {BOOTSTRAP_REPLICAS} replica(s)", flush=True)
        request(
            "PATCH", group_path(), {"replicas": BOOTSTRAP_REPLICAS},
            content_type="application/merge-patch+json",
        )
        group = wait_for_settle()
        if group.get("replicas") != BOOTSTRAP_REPLICAS:
            raise RuntimeError("Bootstrap PATCH returned but replica target was not confirmed")
    else:
        print(f"Bootstrap: {BOOTSTRAP_REPLICAS} replica(s) already requested; no PATCH", flush=True)

    # Changing replicas on a stopped group does not necessarily start it.
    if (group.get("current_state") or {}).get("status") == "stopped":
        print(f"Starting stopped group {GROUP_NAME}", flush=True)
        request("POST", group_path() + "/start")
        deadline = time.monotonic() + SETTLE_TIMEOUT
        while True:
            group = get_group()
            status = (group.get("current_state") or {}).get("status") if group else None
            if group is not None and not group.get("pending_change") and status != "stopped":
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Start accepted but group has not left stopped state")
            time.sleep(SETTLE_POLL_SECONDS)
    print(f"Bootstrap verified: requested replicas={BOOTSTRAP_REPLICAS}", flush=True)


def report(gpu_id, apply, bootstrap=False):
    if bootstrap and not apply:
        raise RuntimeError("--bootstrap requires --apply")
    queue = get_queue()
    group = get_group()
    print(f"Organization/Project: {ORG}/{PROJECT}")
    print(f"Queue: {QUEUE_NAME} ({'FOUND' if queue else 'MISSING'})")
    print(f"Container Group: {GROUP_NAME} ({'FOUND' if group else 'MISSING'})")
    print(f"GPU: {GPU_NAME}; CPU: {RESOURCE_SPEC['cpu']}; RAM: {RESOURCE_SPEC['memory']} MB")
    print(f"Shared memory: {RESOURCE_SPEC['shm_size']} MB; Disk: {RESOURCE_SPEC['storage_amount']} bytes")
    print(f"Priority: {PRIORITY}; initial/min/max replicas: {INITIAL_REPLICAS}/{MIN_REPLICAS}/{MAX_REPLICAS}")
    print(f"Bootstrap replicas: {BOOTSTRAP_REPLICAS}; requested: {bootstrap}")
    print(f"Image: {IMAGE}", flush=True)
    if group is not None:
        assert_queue_connection(group)
        drift = config_drift(group, gpu_id)
        print("Configuration drift:", ", ".join(drift) if drift else "none")
        if (group.get("replicas") or 0) > 0 and drift and apply:
            raise RuntimeError("Group has running replicas; stop/drain it manually before updating")
    if not apply:
        print("READ-ONLY CHECK: use --apply to create/reconcile named resources.")
        return
    ensure_queue()
    group = ensure_group(gpu_id, bootstrap=bootstrap)
    group = wait_for_settle()
    assert_queue_connection(group)
    drift = config_drift(group, gpu_id)
    if drift:
        if (group.get("replicas") or 0) > 0:
            raise RuntimeError("Group is running; stop/drain before changing configuration")
        print("Repairing existing group: " + ", ".join(drift), flush=True)
        patch_group(gpu_id)
        group = wait_for_settle()
    assert_queue_connection(group)
    remaining = config_drift(group, gpu_id)
    if remaining:
        raise RuntimeError("Post-deploy configuration mismatch: " + ", ".join(remaining))
    if get_queue() is None:
        raise RuntimeError("Queue missing after deployment")
    if bootstrap:
        bootstrap_group(group)
    print("SUCCESS: configured Queue and Container Group verified; no duplicate created.")
    print("Other groups/queues were NOT deleted.")


def main():
    if os.environ.get("DIRECT_QUEUE_ENABLED", "false").lower() == "true":
        raise SystemExit("Direct queue mode uses the Backend Settings > Deploy saved draft. "
                         "The legacy Salad queue CLI is disabled to prevent accidental reattachment.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create/reconcile only the configured Queue/Group")
    parser.add_argument(
        "--bootstrap", action="store_true",
        help="With --apply, explicitly request one replica (may incur GPU charges)",
    )
    parser.add_argument("--priority", help="Compatibility only; must match SALAD_PRIORITY in .env")
    args = parser.parse_args()
    validate_configuration()
    if args.bootstrap and not args.apply:
        parser.error("--bootstrap requires --apply")
    if args.priority is not None and args.priority != PRIORITY:
        parser.error("--priority must match SALAD_PRIORITY in .env")
    gpu_id = select_gpu()
    report(gpu_id, args.apply, bootstrap=args.bootstrap)


if __name__ == "__main__":
    main()
