"""Minimal, credential-safe Salad Container Group operations.

Never return the raw Container Group to the browser: its environment may contain
R2 credentials. Control is scoped to the ONE group configured by .env.
"""
import httpx
import json
import os
import re
import time
import threading
from uuid import uuid4
from . import settings_store, db, direct_queue, instance_contract
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


def _provider_call(method, suffix="", *, json_body=None):
    """Return only a sanitized control result: HTTP status and no body data."""
    headers = salad.headers()
    if json_body is not None:
        headers["Content-Type"] = "application/merge-patch+json"
    with httpx.Client(timeout=settings.salad_http_timeout_seconds) as client:
        response = client.request(method, group_url() + suffix, headers=headers, json=json_body)
        response.raise_for_status()
        return response.status_code


_OPERATION_ACTIVE = ("requested", "awaiting_confirmation", "unconfirmed")


def _reserve_operation(action, source, target):
    group_name = settings.salad_group_name
    target_json = json.dumps(target or {}, sort_keys=True, separators=(",", ":"))
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        slots = ",".join("?" for _ in _OPERATION_ACTIVE)
        row = c.execute(
            f"SELECT * FROM instance_operations WHERE group_name=? AND status IN ({slots}) ORDER BY requested_at DESC LIMIT 1",
            (group_name, *_OPERATION_ACTIVE),
        ).fetchone()
        if row:
            existing = dict(row)
            same_target = existing.get("action") == action and existing.get("target_json") == target_json
            if same_target:
                return {"operation_id": existing["operation_id"], "status": existing["status"],
                        "duplicate": True, "requested_at": existing["requested_at"]}
            raise ValueError("Another provider operation is awaiting confirmation; refresh the Infrastructure status")
        operation_id = str(uuid4())
        requested_at = db.utcnow()
        c.execute(
            "INSERT INTO instance_operations(operation_id,group_name,action,source,status,requested_at,target_json,safe_detail) VALUES (?,?,?,?,?,?,?,?)",
            (operation_id, group_name, action, source, "requested", requested_at, target_json,
             "Controller reserved the operation before calling Salad"),
        )
    return {"operation_id": operation_id, "status": "requested", "duplicate": False,
            "requested_at": requested_at}


def _operation_update(operation_id, *, status, detail, provider_response_at=None):
    with db.connect() as c:
        c.execute("UPDATE instance_operations SET status=?,safe_detail=?,provider_response_at=? WHERE operation_id=?",
                  (status, detail, provider_response_at, operation_id))


def _apply_provider_operation(action, source, target, method, suffix="", *, payload=None, message=""):
    reserved = _reserve_operation(action, source, target)
    if reserved["duplicate"]:
        return {"accepted": False, "pending": True, "operation_id": reserved["operation_id"],
                "status": reserved["status"], "message": "The same request is already awaiting provider confirmation"}
    try:
        status_code = _provider_call(method, suffix, json_body=payload)
    except httpx.HTTPStatusError:
        _operation_update(reserved["operation_id"], status="failed",
                          detail="Provider request failed; refresh before retrying")
        raise
    except Exception:
        # A timeout can happen after Salad accepted the request. Keep the
        # operation fenced until a later provider observation resolves it.
        _operation_update(reserved["operation_id"], status="unconfirmed",
                          detail="Provider response was unavailable; outcome is unconfirmed, so no automatic retry was sent")
        raise
    response_at = db.utcnow()
    _operation_update(reserved["operation_id"], status="awaiting_confirmation",
                      detail="Provider accepted the request; waiting for an observed target state",
                      provider_response_at=response_at)
    return {"accepted": True, "pending": True, "operation_id": reserved["operation_id"],
            "status": "awaiting_confirmation", "provider_http_status": status_code,
            "message": message or "Provider accepted the operation; refresh status to confirm completion"}


def _adopt_provider_transition(action, source, target, detail):
    """Track an in-flight transition already visible at the provider."""
    reserved = _reserve_operation(action, source, target)
    if not reserved["duplicate"]:
        _operation_update(reserved["operation_id"], status="awaiting_confirmation", detail=detail,
                          provider_response_at=db.utcnow())
    return {"accepted": False, "pending": True, "operation_id": reserved["operation_id"],
            "status": "awaiting_confirmation", "message": detail}


def _activity_stop_guard():
    activity = db.activity_counts()
    if activity["stop_blocked"]:
        raise ValueError(
            "Stop is blocked while Jobs are pending, running, finalizing/transferring, or have uncertain status "
            f"(pending={activity['pending']}, running={activity['running']}, "
            f"finalizing={activity['finalizing']}, uncertain={activity['uncertain']})"
        )
    return activity


def status(*, group_data=None):
    configured_group = settings.salad_group_name
    version, observed_at = instance_contract.begin(configured_group)
    group = group_data if isinstance(group_data, dict) else request("GET")
    response = request("GET", "/instances")
    instances = response.get("instances", []) if isinstance(response, dict) else response
    if not isinstance(instances, list):
        instances = []
    state = group.get("current_state") or {}
    is_direct = direct_queue.enabled()
    if settings.salad_group_name != configured_group:
        raise ValueError("Active group changed during observation; refresh its status")
    result = {
        "queue_mode": "direct" if is_direct else "salad_queue",
        "auto_gpu_control": os.getenv("DIRECT_GPU_AUTO_CONTROL", "false").lower() == "true" if is_direct else None,
        "hold": direct_queue.load_setting("direct_hold", False) if is_direct else False,
        "name": group.get("name") or configured_group,
        "status": state.get("status"),
        "pending_change": bool(group.get("pending_change")),
        "replicas": group.get("replicas"),
        "counts": state.get("instance_status_counts") or {},
        "autoscaler_enabled": bool(group.get("queue_autoscaler")),
        "keep_warm": bool(direct_queue.load_setting("direct_keep_warm", False)) if is_direct else (group.get("queue_autoscaler") or {}).get("min_replicas") == 1,
        "min_replicas": (1 if direct_queue.load_setting("direct_keep_warm", False) else 0) if is_direct else (group.get("queue_autoscaler") or {}).get("min_replicas"),
        "max_replicas": 1 if is_direct else (group.get("queue_autoscaler") or {}).get("max_replicas"),
        "instances": [{
            "id": item.get("id"),
            "state": item.get("state"),
            "ready": item.get("ready"),
            "pulling_progress": item.get("pulling_progress"),
            "pulling_progress_unit": item.get("pulling_progress_unit"),
            "pulling_progress_total": item.get("pulling_progress_total"),
            "update_time": item.get("update_time"),
        } for item in instances if isinstance(item, dict)],
    }
    return instance_contract.record(result, version, observed_at)


def stop(source="admin", *, hold_shutdown=False):
    # Group has MAX_REPLICAS=1. Stopping the group stops its only worker and
    # prevents an autoscaler from immediately replacing a stopped instance.
    group = request("GET")
    if group.get("pending_change"):
        raise ValueError("A Salad configuration change is still pending")
    _activity_stop_guard()
    if direct_queue.enabled():
        if direct_queue.load_setting("direct_keep_warm", False) and not hold_shutdown:
            raise ValueError("Keep Warm is enabled. Disable it before stopping")
    elif int((group.get("queue_autoscaler") or {}).get("min_replicas", 0)) == 1:
        raise ValueError("Keep Warm is enabled. Return to Auto first, then Stop.")
    current_state = str((group.get("current_state") or {}).get("status") or "").lower()
    if current_state == "stopped":
        return {"accepted": False, "pending": False, "message": "Already stopped"}
    if current_state in {"stopping", "deleting"}:
        return _adopt_provider_transition("stop", source, {"status": "stopped"},
                                          "Salad is already stopping the group; waiting for stopped state and zero instances")
    result = _apply_provider_operation("stop", source, {"status": "stopped"}, "POST", "/stop",
                                       message="Stop request accepted; waiting for Salad to report stopped with zero instances")
    if direct_queue.enabled():
        direct_queue.save_setting("direct_boot_started", 0)
    return result


def start(source="admin"):
    group = request("GET")
    if group.get("pending_change"):
        raise ValueError("A Salad configuration change is still pending")
    state = str((group.get("current_state") or {}).get("status") or "").lower()
    if state != "stopped":
        if state in {"starting", "provisioning", "creating"}:
            return _adopt_provider_transition("start", source, {"status": "started"},
                                              "Salad is already starting the group; waiting for observed start state")
        return {"accepted": False, "pending": False, "message": "Group is already started"}
    return _apply_provider_operation("start", source, {"status": "started"}, "POST", "/start",
                                     message="Start accepted; waiting for Salad to confirm the group is starting")


def set_replicas(replicas, source="admin"):
    if replicas not in (0, 1):
        raise ValueError("This controller supports only zero or one GPU replica")
    group = request("GET")
    if group.get("pending_change"):
        raise ValueError("A Salad configuration change is still pending")
    state = str((group.get("current_state") or {}).get("status") or "").lower()
    current = int(group.get("replicas") or 0)
    if replicas == 1:
        if state == "stopped":
            raise ValueError("Start the group before requesting a replica")
        if current >= 1:
            return {"accepted": False, "pending": state in {"starting", "provisioning"},
                    "message": "One replica is already requested"}
    else:
        _activity_stop_guard()
        if direct_queue.enabled() and direct_queue.load_setting("direct_keep_warm", False):
            raise ValueError("Keep Warm is enabled; turn it off before scaling to zero")
        if not direct_queue.enabled() and int((group.get("queue_autoscaler") or {}).get("min_replicas", 0)) > 0:
            raise ValueError("Keep Warm requires at least one replica; return to Auto before scaling to zero")
        if current == 0:
            return {"accepted": False, "pending": False, "message": "Zero replicas are already requested"}
    result = _apply_provider_operation("replica" if replicas else "scale_down", source,
        {"replicas": replicas}, "PATCH", payload={"replicas": replicas},
        message=("One GPU replica request accepted; waiting for provider confirmation" if replicas
                 else "Scale-to-zero request accepted; waiting for provider confirmation"))
    if direct_queue.enabled():
        direct_queue.save_setting("direct_boot_started", time.time() if replicas else 0)
    return result


def request_one_replica(source="admin"):
    return set_replicas(1, source=source)


def set_keep_warm(enabled, source="admin"):
    """Change ONLY the autoscaler's 0/1 minimum; never change image or resources.

    PATCH may be asynchronous. Do not request additional replicas until a
    subsequent status() confirms pending_change=False. Changing configuration
    can reallocate instances; it cannot guarantee retaining physical hardware.
    """
    group = request("GET")
    if group.get("pending_change"):
        raise ValueError("A Salad configuration change is pending; refresh and retry")
    if not enabled:
        _activity_stop_guard()
    if direct_queue.enabled():
        if enabled and (group.get("current_state") or {}).get("status") == "stopped":
            raise ValueError("Start the group first, then enable Keep Warm")
        current = bool(direct_queue.load_setting("direct_keep_warm", False))
        if current == bool(enabled):
            return {"accepted": False, "pending": False, "message": "Keep Warm is already " + ("ON" if enabled else "OFF")}
        reserved = _reserve_operation("keep_warm", source, {"min_replicas": 1 if enabled else 0})
        if reserved["duplicate"]:
            return {"accepted": False, "pending": True, "operation_id": reserved["operation_id"],
                    "status": reserved["status"], "message": "Keep Warm change is already recorded"}
        direct_queue.save_setting("direct_keep_warm", bool(enabled))
        _operation_update(reserved["operation_id"], status="confirmed", detail="Local scheduler policy was saved",
                          provider_response_at=db.utcnow())
        return {"accepted": True, "pending": False, "operation_id": reserved["operation_id"], "message":
            "Direct Keep Warm enabled; one requested GPU will remain allocated until turned off" if enabled
            else "Direct Keep Warm disabled; GPU auto-stop requires DIRECT_GPU_AUTO_CONTROL=true (or use Stop manually)"}
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
    result = _apply_provider_operation("keep_warm", source, {"min_replicas": target}, "PATCH",
                                       payload={"queue_autoscaler": updated},
                                       message="Keep Warm setting accepted; waiting for Salad to confirm the autoscaler minimum")
    if enabled:
        message = ("Keep Warm requested (minimum 1 GPU). Wait until pending change "
                   "clears; if there is no instance, press Start 1 GPU replica. "
                   "GPU billing continues while idle.")
    else:
        message = ("Auto scale-to-zero requested (minimum 0 GPUs). "
                   "Salad may take time to drain the queue and scale down. "
                   "Check instances before assuming billing has stopped.")
    result["message"] = message
    return result


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
    if direct_queue.enabled():
        backend_url = os.environ.get("DIRECT_BACKEND_URL", "").strip().rstrip("/")
        worker_token = os.environ.get("DIRECT_WORKER_TOKEN", "")
        if not backend_url.startswith("https://") or len(worker_token) < 32:
            raise ValueError("Set HTTPS DIRECT_BACKEND_URL and strong DIRECT_WORKER_TOKEN in private .env")
        env["DIRECT_BACKEND_URL"] = backend_url
        env["DIRECT_WORKER_TOKEN"] = worker_token
        env["DIRECT_WORKER_JOB_TIMEOUT_SECONDS"] = os.environ.get("DIRECT_WORKER_JOB_TIMEOUT_SECONDS", "3600")
    if _env_int("SALAD_MAX_REPLICAS") != 1:
        raise ValueError("This controller supports one GPU replica only")
    if _env_int("SALAD_MIN_REPLICAS") != 0:
        raise ValueError("New groups must begin with min_replicas=0")
    if direct_queue.enabled():
        # Never attach a Salad queue/autoscaler or inherit the temporary IMDS
        # test command. This must be a NEW group, not an in-place conversion.
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
            "restart_policy": "never",  # no automatic crash/download loop
            "autostart_policy": False,
            "readiness_probe": _probe("SALAD_READINESS", "SALAD_READINESS_PATH"),
            "startup_probe": _probe("SALAD_STARTUP", "SALAD_STARTUP_PATH"),
        }
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
    # Preserve historic Salad jobs in their original queue. They can be
    # inspected but are NEVER silently converted or dispatched on the new GPU.
    if direct_queue.enabled():
        return
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
        if not direct_queue.enabled():
            _ensure_queue()
        if direct_queue.enabled() and desired["group_name"] == current["group_name"] and old_group and (old_group.get("queue_connection") or old_group.get("queue_autoscaler")):
            raise ValueError("Direct queue migration requires a NEW Container Group name; the legacy group is preserved")
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
        verified_group = _wait_settled(candidate, desired["image"])
        if direct_queue.enabled() and (verified_group.get("queue_connection") or verified_group.get("queue_autoscaler") or verified_group.get("restart_policy") != "never"):
            raise ValueError("New group still has a Salad Queue/autoscaler or restart policy mismatch; not activating")
        # Stop only the OLD idle group, and never silently delete it.
        if old_group and (old_group.get("current_state") or {}).get("status") != "stopped":
            _api("POST", _group_path(current["group_name"]) + "/stop")
        resolved = {**desired, "group_name": candidate}
        return {"accepted": True,
                "message": "New group provisioned; old idle group stopped and preserved",
                **settings_store.activate(resolved)}
    finally:
        _deploy_lock.release()
