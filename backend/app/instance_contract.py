"""PDF-45/47: conservative, credential-free infrastructure observations.

Versions belong to controller observations of one group, not provider events.
Observed sessions do not assert billing boundaries or selected-model readiness.
"""
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

from . import db, direct_queue


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch else None


def begin(group_name):
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        key = "instance_sequence:" + group_name
        row = c.execute("SELECT value FROM controller_settings WHERE key=?", (key,)).fetchone()
        version = int(row["value"]) + 1 if row else 1
        c.execute("INSERT INTO controller_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(version)))
    return version, db.utcnow()


def record(data, version, observed_at):
    group_name = data["name"]
    now = time.time()
    hello = direct_queue.load_setting("direct_worker_seen", {}) or {}
    with db.connect() as c:
        row = c.execute("SELECT MAX(last_heartbeat) at FROM jobs WHERE execution_mode='direct' AND state IN ('running','finalizing') AND lease_deadline>=?", (now,)).fetchone()
    heartbeat = max(float(hello.get("at", 0) or 0), float(row["at"] or 0))
    observed = data["instances"]
    # Allocation disappearance cannot leave a ghost worker looking connected.
    fresh = bool(observed and heartbeat and now - heartbeat <= 90 and not data.get("hold"))
    worker_status = "connected" if fresh else "stale" if heartbeat and observed else "unknown"
    instances = [{**item, "provider_status": item.get("state"),
        "provider_ready": item.get("ready"), "ready": None,
        "readiness": None, "readiness_reason": "Selected-tool readiness is not reported by the current worker",
        "last_updated_at": item.get("update_time") or observed_at,
        "pull_progress": {"value": item.get("pulling_progress"), "unit": None,
                          "scope": "image_pull", "source": "salad_provider",
                          "updated_at": item.get("update_time") or observed_at}}
        for item in observed]
    result = {**data, "group_name": group_name, "provider_status": data["status"],
              "desired_replicas": data["replicas"], "observed_instances": len(instances), "instances": instances,
              "pending_operation": "provider_change" if data["pending_change"] else None,
              "version": version, "version_source": "controller_observation",
              "last_updated_at": observed_at, "freshness": {"source": "controller_observation", "stale_after_seconds": 30},
              "worker_status": worker_status, "last_heartbeat_at": iso(heartbeat),
              "readiness": None, "model_readiness": None, "capabilities": None,
              "readiness_reason": "Worker communication is observed separately; model/tool readiness is unknown",
              "financial": {"hourly_rate": None, "currency": None, "rate_source": None, "rate_updated_at": None,
                            "estimated_cost": None, "estimate_source": None, "balance": None, "balance_updated_at": None,
                            "billing": None, "billing_source": None, "billing_updated_at": None,
                            "limitation": "No verified rate, balance or billing API is configured"}}
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        previous = c.execute("SELECT version,snapshot_json FROM instance_observations WHERE group_name=?", (group_name,)).fetchone()
        if previous and previous["version"] >= version:
            return json.loads(previous["snapshot_json"])
        current_ids = {str(item["id"]) for item in instances if item.get("id")}
        sessions = c.execute("SELECT * FROM instance_sessions WHERE group_name=? AND stopped_at IS NULL", (group_name,)).fetchall()
        for session in sessions:
            intervals = json.loads(session["intervals_json"])
            if session["instance_id"] not in current_ids:
                intervals[-1]["stopped_at"] = observed_at
                c.execute("UPDATE instance_sessions SET stopped_at=?,intervals_json=? WHERE session_id=?", (observed_at, json.dumps(intervals), session["session_id"]))
            else:
                intervals[-1]["last_observed_at"] = observed_at
                c.execute("UPDATE instance_sessions SET last_observed_at=?,intervals_json=? WHERE session_id=?", (observed_at, json.dumps(intervals), session["session_id"]))
                current_ids.remove(session["instance_id"])
        for instance_id in sorted(current_ids):
            interval = {"started_at": observed_at, "last_observed_at": observed_at, "stopped_at": None,
                        "source": "controller_observation"}
            c.execute("INSERT INTO instance_sessions(session_id,group_name,instance_id,started_at,last_observed_at,intervals_json) VALUES (?,?,?,?,?,?)", (str(uuid4()), group_name, instance_id, observed_at, observed_at, json.dumps([interval])))
        result["sessions"] = []
        for row in c.execute("SELECT * FROM instance_sessions WHERE group_name=? ORDER BY started_at DESC LIMIT 100", (group_name,)):
            session = dict(row)
            session["activity_intervals"] = json.loads(session.pop("intervals_json"))
            session["source"] = "controller_observation"
            session["billing_boundaries_known"] = False
            result["sessions"].append(session)
        c.execute("INSERT INTO instance_observations(group_name,version,updated_at,snapshot_json) VALUES (?,?,?,?) ON CONFLICT(group_name) DO UPDATE SET version=excluded.version,updated_at=excluded.updated_at,snapshot_json=excluded.snapshot_json", (group_name, version, observed_at, json.dumps(result)))
    return result
