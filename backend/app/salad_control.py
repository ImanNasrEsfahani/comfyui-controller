"""Minimal, credential-safe Salad Container Group operations.

Never return the raw Container Group to the browser: its environment may contain
R2 credentials. Control is scoped to the ONE group configured by .env.
"""
import httpx
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
