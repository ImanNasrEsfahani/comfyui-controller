"""Minimal, credential-safe Salad Container Group operations.

Never return the raw Container Group to the browser: its environment may contain
R2 credentials. Control is scoped to the ONE group configured by .env.
"""
import httpx
import os
import re
import time
import threading
from uuid import uuid4
from . import settings_store, db
from .config import settings
from . import salad


def group_url():
    return (f"{settings.salad_api_base_url}/organizations/{settings.salad_org}"
            f"/projects/{settings.salad_project}/containers/{settings.salad_group_name}")


def request(method, suffix="", *, json_body=None):
    headers = salad.headers()
    if json_body is not None:
        headers["Content-Type"] = "application/merge-patch+json"
    with httpx.Client(timeout=settings.salad_http_timeout_seconds) as client:
        r = client.request(method, group_url() + suffix, headers=headers, json=json_body)
        r.raise_for_status()
        return r.json() if r.content else {}


def status():
    group = request("GET")
    response = request("GET", "/instances")
    instances = response.get("instances", []) if isinstance(response, dict) else response
    if not isinstance(instances, list):
        instances = []
    state = group.get("current_state") or {}
    return {
        "name": group.get("name"),
        "status": state.get("status"),
        "pending_change": bool(group.get("pending_change")),
        "replicas": group.get("replicas", 0),
        "counts": state.get("instance_status_counts") or {},
        "autoscaler_enabled": bool(group.get("queue_autoscaler")),
        "keep_warm": (group.get("queue_autoscaler") or {}).get("min_replicas") == 1,
        "min_replicas": (group.get("queue_autoscaler") or {}).get("min_replicas"),
        "max_replicas": (group.get("queue_autoscaler") or {}).get("max_replicas"),
        "instances": [{
            "id": item.get("id"),
            "state": item.get("state"),
            "ready": item.get("ready", False),
            "pulling_progress": item.get("pulling_progress"),
            "update_time": item.get("update_time"),
        } for item in instances if isinstance(item, dict)],
    }


def stop():
    # Group has MAX_REPLICAS=1. Stopping the group stops its only worker and
    # prevents an autoscaler from immediately replacing a stopped instance.
    group = request("GET")
    if group.get("pending_change"):
        raise ValueError("A Salad configuration change is still pending")
    if int((group.get("queue_autoscaler") or {}).get("min_replicas", 0)) == 1:
        raise ValueError("Keep Warm is enabled. Return to Auto first, then Stop.")
    if (group.get("current_state") or {}).get("status") == "stopped":
        return {"accepted": False, "message": "Already stopped"}
    request("POST", "/stop")
    return {"accepted": True, "message": "Stop requested for the container group"}


def start():
    group = request("GET")
    if group.get("pending_change"):
        raise ValueError("A Salad configuration change is still pending")
    if (group.get("current_state") or {}).get("status") != "stopped":
        return {"accepted": False, "message": "Group is not stopped"}
    request("POST", "/start")
    return {"accepted": True, "message": "Start requested; request 1 replica once settled"}


def request_one_replica():
    group = request("GET")
    if group.get("pending_change"):
        raise ValueError("A Salad configuration change is still pending")
    if (group.get("current_state") or {}).get("status") == "stopped":
        raise ValueError("Start the group before requesting a replica")
    if (group.get("replicas") or 0) >= 1:
        return {"accepted": False, "message": "One replica is already requested"}
    request("PATCH", json_body={"replicas": 1})
    return {"accepted": True, "message": "One replica requested"}


def set_keep_warm(enabled):
    """Change ONLY the autoscaler's 0/1 minimum; never change image or resources.

    PATCH may be asynchronous. Do not request additional replicas until a
    subsequent status() confirms pending_change=False. Changing configuration
    can reallocate instances; it cannot guarantee retaining physical hardware.
    """
    group = request("GET")
    if group.get("pending_change"):
        raise ValueError("A Salad configuration change is pending; refresh and retry")
    config = group.get("queue_autoscaler")
    if not isinstance(config, dict):
        raise ValueError("This group has no queue autoscaler; refusing to change it")
    if int(config.get("max_replicas", -1)) != 1:
        raise ValueError("Expected a single-GPU group (max_replicas=1)")
    current = int(config.get("min_replicas", -1))
    if current not in (0, 1):
        raise ValueError("Unexpected autoscaler minimum; refusing to overwrite it")
    target = 1 if enabled else 0
    if enabled and (group.get("current_state") or {}).get("status") == "stopped":
        raise ValueError("Start the Container Group first, then enable Keep Warm")
    if current == target:
        return {"accepted": False, "message": "Keep Warm is already " + ("ON" if enabled else "OFF")}

    allowed = (
        "desired_queue_length", "max_downscale_per_minute", "max_replicas",
        "max_upscale_per_minute", "min_replicas", "polling_period",
    )
    updated = {key: config[key] for key in allowed if key in config}
    updated["min_replicas"] = target
    request("PATCH", json_body={"queue_autoscaler": updated})
    if enabled:
        message = ("Keep Warm requested (minimum 1 GPU). Wait until pending change "
                   "clears; if there is no instance, press Start 1 GPU replica. "
                   "GPU billing continues while idle.")
    else:
        message = ("Auto scale-to-zero requested (minimum 0 GPUs). "
                   "Salad may take time to drain the queue and scale down. "
                   "Check instances before assuming billing has stopped.")
    return {"accepted": True, "message": message}


# Never allow concurrent deployments to race with changing the active group.
_deploy_lock = threading.Lock()


def _api(method, path, *, payload=None, allow_missing=False):
    """Restricted Salad control-plane request; do not return secrets to UI."""
    headers = salad.headers()
    if payload is not None and method == "PATCH":
        headers["Content-Type"] = "application/merge-patch+json"
    with httpx.Client(timeout=settings.salad_http_timeout_seconds) as client:
        response = client.request(
            method, settings.salad_api_base_url + path,
            headers=headers, json=payload,
        )
        if allow_missing and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json() if response.content else {}


def _project_path():
    return f"/organizations/{settings.salad_org}/projects/{settings.salad_project}"


def _group_path(name):
    return _project_path() + "/containers/" + name


def _get_group(name):
    return _api("GET", _group_path(name), allow_missing=True)


def _env_int(key):
    raw = os.environ.get(key, "").strip()
    if not raw or not raw.isdigit():
        raise ValueError("Missing or invalid integer in private .env: " + key)
    return int(raw)


def _probe(prefix, path_key):
    return {
        "http": {"path": os.environ[path_key],
                 "port": _env_int("SALAD_WORKER_PORT"),
                 "scheme": os.environ["SALAD_WORKER_SCHEME"], "headers": []},
        "initial_delay_seconds": _env_int(prefix + "_INITIAL_DELAY_SECONDS"),
        "period_seconds": _env_int(prefix + "_PERIOD_SECONDS"),
        "timeout_seconds": _env_int(prefix + "_TIMEOUT_SECONDS"),
        "success_threshold": _env_int(prefix + "_SUCCESS_THRESHOLD"),
        "failure_threshold": _env_int(prefix + "_FAILURE_THRESHOLD"),
    }


def _new_group_payload(config, gpu_id):
    env = {
        "MANIFEST": os.environ["SALAD_MANIFEST_PATH"],
        "PORT": str(_env_int("SALAD_WORKER_PORT")),
        "LRU_CACHE_SIZE_GB": str(_env_int("SALAD_LRU_CACHE_SIZE_GB")),
        "SALAD_LOG_LEVEL": os.environ["SALAD_LOG_LEVEL"],
        "READY_TIMEOUT_SECONDS": str(_env_int("SALAD_READY_TIMEOUT_SECONDS")),
        "STARTUP_CHECK_MAX_TRIES": str(_env_int("SALAD_STARTUP_CHECK_MAX_TRIES")),
        "STARTUP_CHECK_INTERVAL_S": str(_env_int("SALAD_STARTUP_CHECK_INTERVAL_S")),
        "AWS_ACCESS_KEY_ID": settings.r2_access_key_id,
        "AWS_SECRET_ACCESS_KEY": settings.r2_secret_access_key,
        "AWS_REGION": settings.r2_region,
        "AWS_ENDPOINT_URL_S3": settings.r2_endpoint_url,
        "AWS_ENDPOINT_URL": settings.r2_endpoint_url,
    }
    if os.environ.get("HF_TOKEN", "").strip():
        env["HF_TOKEN"] = os.environ["HF_TOKEN"].strip()
    if _env_int("SALAD_MAX_REPLICAS") != 1:
        raise ValueError("This controller supports one GPU replica only")
    if _env_int("SALAD_MIN_REPLICAS") != 0:
        raise ValueError("New groups must begin with min_replicas=0")
    return {
        "name": config["group_name"],
        "display_name": config["display_name"],
        "container": {
            "image": config["image"],
            "priority": settings.salad_priority,
            "resources": {
                "cpu": _env_int("SALAD_CPU"),
                "memory": _env_int("SALAD_MEMORY_MB"),
                "shm_size": _env_int("SALAD_SHM_MB"),
                "storage_amount": _env_int("SALAD_STORAGE_GB") * 1024 ** 3,
                "gpu_classes": [gpu_id],
            },
            "environment_variables": env,
        },
        "replicas": 0,
        "restart_policy": os.environ["SALAD_RESTART_POLICY"],
        "autostart_policy": os.environ.get("SALAD_AUTOSTART_POLICY", "true").lower() == "true",
        "queue_connection": {
            "path": os.environ["SALAD_QUEUE_CONNECTION_PATH"],
            "port": _env_int("SALAD_WORKER_PORT"),
            "queue_name": settings.salad_queue_name(),
        },
        "queue_autoscaler": {
            "min_replicas": 0,
            "max_replicas": 1,
            "desired_queue_length": _env_int("SALAD_DESIRED_QUEUE_LENGTH"),
            "polling_period": _env_int("SALAD_POLLING_PERIOD"),
            "max_upscale_per_minute": _env_int("SALAD_MAX_UPSCALE_PER_MINUTE"),
            "max_downscale_per_minute": _env_int("SALAD_MAX_DOWNSCALE_PER_MINUTE"),
        },
        "readiness_probe": _probe("SALAD_READINESS", "SALAD_READINESS_PATH"),
        "startup_probe": _probe("SALAD_STARTUP", "SALAD_STARTUP_PATH"),
    }


def _ensure_queue():
    path = _project_path() + "/queues"
    name = settings.salad_queue_name()
    if _api("GET", path + "/" + name, allow_missing=True) is None:
        _api("POST", path, payload={"name": name,
             "display_name": os.environ["SALAD_QUEUE_DISPLAY_NAME"]})


def _selected_gpu_id():
    data = _api("GET", f"/organizations/{settings.salad_org}/gpu-classes")
    items = data if isinstance(data, list) else data.get("items", [])
    matches = [x for x in items if
               " ".join(str(x.get("name", "")).lower().split()) ==
               " ".join(settings.salad_gpu_name.lower().split())]
    if len(matches) != 1:
        raise ValueError("Salad GPU class was not uniquely identified")
    return matches[0]["id"]


def _wait_settled(name, image, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        group = _get_group(name)
        if group and not group.get("pending_change") and \
                (group.get("container") or {}).get("image") == image:
            return group
        time.sleep(2)
    raise ValueError(
        "Salad accepted the deployment but is still processing it. "
        "Settings remain unchanged; wait and press Deploy again."
    )


def _assert_safe_to_switch(current, group):
    if not group:
        return
    if group.get("pending_change"):
        raise ValueError("Active group has a pending change; wait before deploying")
    if (group.get("replicas") or 0) > 0 or \
            int((group.get("queue_autoscaler") or {}).get("min_replicas", 0)) > 0:
        raise ValueError("Active GPU or Keep Warm is on. Return to Auto and wait for 0 replicas before Deploy")
    # A job can still be outstanding even after the GPU has disappeared.
    unfinished = {"pending", "running", "stalled", "created"}
    for job in db.list_jobs(100):
        if job.get("state") in unfinished and \
                job.get("salad_queue") == settings.salad_queue_name():
            raise ValueError("A local job is not terminal. Refresh its Salad status and resolve it before switching groups")


def deploy_draft():
    """Create/reconcile idle group; rename on reserved names; commit DB only on success.

    Old groups are never deleted. Switching groups stops the old idle group so
    the same queue is not serviced by both old and new workers.
    """
    if not _deploy_lock.acquire(blocking=False):
        raise ValueError("A deployment is already in progress")
    try:
        state = settings_store.snapshot()
        current, desired = state["active"], dict(state["draft"])
        if not state["has_changes"]:
            return {"accepted": False, "message": "No changes to deploy", **state}
        old_group = _get_group(current["group_name"])
        _assert_safe_to_switch(current, old_group)
        _ensure_queue()
        same_name = desired["group_name"] == current["group_name"]
        same_display = desired["display_name"] == current["display_name"]
        # Safe in-place image update if the active group is idle and the name
        # and display label have not changed.
        if same_name and same_display and old_group:
            if (old_group.get("container") or {}).get("image") != desired["image"]:
                _api("PATCH", _group_path(current["group_name"]),
                     payload={"container": {"image": desired["image"]}})
            _wait_settled(current["group_name"], desired["image"])
            return {"accepted": True, "message": "Existing idle group image updated", 
                    **settings_store.activate(desired)}

        gpu_id = _selected_gpu_id()
        pending = state.get("provisioning")
        if pending and pending.get("draft") == desired:
            candidate = pending["group_name"]
        else:
            candidate = desired["group_name"]
        # A changed display_name of the current group is a NEW deployment,
        # not an attempt to relabel a group with a possibly running history.
        if same_name or (candidate == current["group_name"] and old_group):
            candidate = (candidate[:52].rstrip("-") + "-" + uuid4().hex[:8])
        group = None
        for _ in range(8):
            existing = _get_group(candidate)
            if existing is not None:
                if not (pending and pending.get("draft") == desired and
                        pending.get("group_name") == candidate and
                        (existing.get("container") or {}).get("image") == desired["image"]):
                    candidate = desired["group_name"][:52].rstrip("-") + "-" + uuid4().hex[:8]
                    continue
                group = existing
                break
            resolved = {**desired, "group_name": candidate}
            settings_store.provisioning({"draft": desired, "group_name": candidate})
            try:
                _api("POST", _project_path() + "/containers",
                     payload=_new_group_payload(resolved, gpu_id))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 409 and "name_conflict" in exc.response.text:
                    candidate = desired["group_name"][:52].rstrip("-") + "-" + uuid4().hex[:8]
                    pending = None
                    continue
                raise
            group = _wait_settled(candidate, desired["image"])
            break
        if group is None:
            raise ValueError("Salad could not allocate an unused group name after 8 attempts")
        _wait_settled(candidate, desired["image"])
        # Stop only the OLD idle group, and never silently delete it.
        if old_group and (old_group.get("current_state") or {}).get("status") != "stopped":
            _api("POST", _group_path(current["group_name"]) + "/stop")
        resolved = {**desired, "group_name": candidate}
        return {"accepted": True,
                "message": "New group provisioned; old idle group stopped and preserved",
                **settings_store.activate(resolved)}
    finally:
        _deploy_lock.release()
