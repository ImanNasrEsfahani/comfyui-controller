"""Conservative, versioned observations for Salad instances and GPU sessions.

Provider readiness, Worker communication, model readiness, observed runtime,
and estimated cost are separate facts. Polling observations never claim to be
an invoice or an exact provider billing boundary.
"""
import json
import math
import re
import time
from datetime import datetime, timezone
from uuid import uuid4

from . import db, direct_queue
from .config import settings


PHASE_LABELS = {
    "preparing": "Preparing infrastructure",
    "image_pulling": "Downloading image",
    "container_creating": "Creating container",
    "container_starting": "Starting container",
    "provider_readiness": "Waiting for provider readiness",
    "worker_connecting": "Connecting Worker",
    "worker_initializing": "Worker is initializing ComfyUI",
    "worker_ready": "Worker ready",
    "operation_pending": "Provider operation awaiting confirmation",
    "stopping": "Stopping",
    "stopped": "Stopped",
    "failed": "Provider reported an error",
    "unknown": "Current phase is unknown",
}


def iso(epoch):
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc).isoformat() if epoch else None
    except (TypeError, ValueError, OverflowError):
        return None


def epoch(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def normalize_pull_progress(raw, *, unit=None, total=None, source="salad_provider",
                            updated_at=None, instance_id=None):
    """Return an honest image-pull observation; percent is null unless provable."""
    value = raw
    if isinstance(raw, dict):
        value = raw.get("value")
        if value is None:
            value = raw.get("progress")
        if unit is None:
            unit = raw.get("unit")
        if total is None:
            total = raw.get("total")
    normalized_unit = str(unit).strip().lower() if isinstance(unit, str) else None
    if normalized_unit in {"ratio", "fraction"}:
        normalized_unit = "fraction"
    elif normalized_unit in {"percent", "%"}:
        normalized_unit = "percent"
    elif normalized_unit in {"byte", "bytes"}:
        normalized_unit = "bytes"
    else:
        normalized_unit = None

    percent = None
    if _number(value):
        if normalized_unit == "fraction" and 0 <= value <= 1:
            percent = value * 100
        elif normalized_unit == "percent" and 0 <= value <= 100:
            percent = value
        elif normalized_unit == "bytes" and _number(total) and total > 0 and 0 <= value <= total:
            percent = value / total * 100
    if percent is not None:
        percent = round(percent, 4)
    return {
        "scope": "image_pull", "raw_value": value, "raw_total": total,
        "unit": normalized_unit, "percent": percent, "source": source,
        "updated_at": updated_at, "instance_id": str(instance_id) if instance_id is not None else None,
    }


def _worker_observation(now, has_instances):
    direct = direct_queue.enabled()
    hello = direct_queue.load_setting("direct_worker_seen", {}) or {}
    try:
        stale_after = direct_queue.integer("DIRECT_WORKER_STATUS_STALE_SECONDS", 90, 30, 3600)
    except ValueError:
        stale_after = 90
    hello_at = float(hello.get("at", 0) or 0)
    last_at = hello_at
    age = max(0.0, now - last_at) if last_at else None
    fresh_hello = bool(hello_at and now - hello_at <= stale_after)
    if not has_instances:
        status = "disconnected" if direct else "unknown"
    elif direct and fresh_hello:
        status = "connected"
    elif direct and last_at:
        status = "stale"
    elif direct:
        status = "disconnected"
    else:
        # Legacy Salad Queue workers are represented by provider health checks;
        # they do not send this controller's authenticated direct-worker hello.
        status = "unknown"
    runtime_ready = hello.get("runtime_ready") if fresh_hello else None
    if not isinstance(runtime_ready, bool):
        runtime_ready = None
    return {
        "status": status,
        "worker_id": hello.get("worker_id") if fresh_hello else None,
        "generation": hello.get("generation") if fresh_hello else None,
        "runtime_readiness": "ready" if runtime_ready is True else "not_ready" if runtime_ready is False else "unknown",
        "runtime_ready": runtime_ready,
        "last_heartbeat_at": iso(last_at),
        "last_heartbeat_source": "authenticated_worker_hello" if hello_at else None,
        "age_seconds": round(age, 3) if age is not None else None,
        "stale_after_seconds": stale_after,
    }


def _phase(group_status, instances, worker, ready, pending_change):
    if pending_change:
        return "operation_pending"
    group = str(group_status or "").strip().lower()
    if group in {"stopped", "terminated"} and not instances:
        return "stopped"
    if group in {"stopping", "deleting"}:
        return "stopping"
    states = [str(item.get("provider_status") or "").strip().lower() for item in instances]
    if any(s in {"failed", "error", "crashed", "unhealthy"} for s in states) or group in {"failed", "error"}:
        return "failed"
    if any("pull" in s for s in states):
        return "image_pulling"
    if any(s in {"pending", "allocating", "preparing", "provisioning"} for s in states):
        return "preparing"
    if any("creat" in s for s in states):
        return "container_creating"
    if any("start" in s for s in states):
        return "container_starting"
    if not instances:
        return "preparing" if group in {"starting", "pending", "provisioning"} else "unknown"
    if any(item.get("provider_ready") is False for item in instances):
        return "provider_readiness"
    if ready:
        return "worker_ready"
    if worker.get("runtime_readiness") == "not_ready":
        return "worker_initializing"
    if worker.get("status") == "connected":
        return "worker_initializing" if worker.get("runtime_readiness") == "unknown" else "worker_connecting"
    return "worker_connecting"


def _readiness(data, instances, worker):
    group_state = str(data.get("status") or "").strip().lower()
    if data.get("hold"):
        return "not_ready", "GPU controller HOLD is active; reset it before processing jobs"
    if data.get("pending_change"):
        return "not_ready", "Salad is applying a provider configuration change"
    if group_state in {"stopped", "stopping", "terminated", "deleting"}:
        return "not_ready", "The provider group is stopped or stopping"
    if not instances:
        return "not_ready", "No active provider instance is observed"
    if len(instances) != 1:
        return "unknown", "This controller cannot verify Worker readiness across multiple replicas"
    if instances[0].get("provider_ready") is False:
        return "not_ready", "Salad readiness probe has not passed"
    instance_state = str(instances[0].get("provider_status") or "").strip().lower()
    if instance_state in {"stopped", "stopping", "terminated", "deleting", "failed", "error", "crashed"}:
        return "not_ready", "The observed provider instance is not active"
    if instances[0].get("provider_ready") is not True:
        return "unknown", "The provider did not report a verified readiness result"
    if worker.get("status") in {"disconnected", "stale"}:
        return "not_ready", "Worker heartbeat is disconnected or expired"
    if worker.get("status") != "connected":
        return "unknown", "A fresh authenticated Worker heartbeat is not available"
    if worker.get("runtime_ready") is False:
        return "not_ready", "Worker cannot currently reach the ComfyUI runtime"
    if worker.get("runtime_ready") is not True:
        return "unknown", "Worker communication is fresh, but ComfyUI runtime readiness is not verified"
    return "ready", "Provider probe and fresh Worker-to-ComfyUI readiness checks passed; selected-model readiness is not checked here"


def _rate_config():
    raw = getattr(settings, "salad_gpu_hourly_rate", "")
    currency = getattr(settings, "salad_gpu_rate_currency", "")
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        rate = None
    if not _number(rate) or rate <= 0 or not re.fullmatch(r"[A-Z]{3}", str(currency or "")):
        return None
    return {"hourly_rate": rate, "currency": currency, "source": "operator_configured_private_env"}


def _operation_target(c, group_name, data, observed_at, instance_count):
    active_states = ("requested", "awaiting_confirmation", "unconfirmed")
    placeholders = ",".join("?" for _ in active_states)
    row = c.execute(
        f"SELECT * FROM instance_operations WHERE group_name=? AND status IN ({placeholders}) ORDER BY requested_at DESC LIMIT 1",
        (group_name, *active_states),
    ).fetchone()
    if not row:
        return None
    op = dict(row)
    try:
        target = json.loads(op.get("target_json") or "{}")
    except (TypeError, ValueError):
        target = {}
    provider_status = str(data.get("status") or "").lower()
    confirmed = False
    if op["action"] == "start":
        confirmed = provider_status in {"starting", "provisioning", "creating", "running", "ready", "active"}
    elif op["action"] == "stop":
        confirmed = provider_status == "stopped" and instance_count == 0
    elif op["action"] in {"replica", "scale_down"}:
        confirmed = data.get("replicas") == target.get("replicas")
    elif op["action"] in {"keep_warm", "auto_scale"}:
        confirmed = (not data.get("pending_change") and
                     data.get("min_replicas") == target.get("min_replicas"))
    if confirmed:
        c.execute("UPDATE instance_operations SET status='confirmed',confirmed_at=?,safe_detail=? WHERE operation_id=?",
                  (observed_at, "Provider state matches the requested target", op["operation_id"]))
        op["status"] = "confirmed"
        op["confirmed_at"] = observed_at
        op["safe_detail"] = "Provider state matches the requested target"
    return {key: op.get(key) for key in (
        "operation_id", "action", "source", "status", "requested_at",
        "provider_response_at", "confirmed_at", "safe_detail")}


def _open_or_rotate_rate(c, session, rate, observed_at):
    current = c.execute(
        "SELECT * FROM instance_cost_periods WHERE session_id=? AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
        (session["session_id"],),
    ).fetchone()
    if not rate:
        if current:
            c.execute("UPDATE instance_cost_periods SET ended_at=? WHERE period_id=? AND ended_at IS NULL",
                      (observed_at, current["period_id"]))
        return
    if current and math.isclose(float(current["hourly_rate"]), rate["hourly_rate"], rel_tol=0, abs_tol=1e-9) and current["currency"] == rate["currency"]:
        return
    if current:
        c.execute("UPDATE instance_cost_periods SET ended_at=? WHERE period_id=? AND ended_at IS NULL",
                  (observed_at, current["period_id"]))
    c.execute(
        """INSERT INTO instance_cost_periods
           (period_id,session_id,group_name,instance_id,started_at,hourly_rate,currency,rate_source,rate_observed_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (str(uuid4()), session["session_id"], session["group_name"], session["instance_id"],
         observed_at, rate["hourly_rate"], rate["currency"], rate["source"], observed_at),
    )


def _close_open_rates(c, session_id, observed_at):
    c.execute("UPDATE instance_cost_periods SET ended_at=? WHERE session_id=? AND ended_at IS NULL",
              (observed_at, session_id))


def _session_cost(c, session_id, now_epoch):
    amounts = {}
    for period in c.execute("SELECT * FROM instance_cost_periods WHERE session_id=?", (session_id,)):
        start = epoch(period["started_at"])
        end = epoch(period["ended_at"]) if period["ended_at"] else now_epoch
        if start is None or end is None:
            continue
        seconds = max(0.0, end - start)
        currency = period["currency"]
        amounts[currency] = amounts.get(currency, 0.0) + float(period["hourly_rate"]) * seconds / 3600.0
    return {code: round(value, 6) for code, value in amounts.items()}


def _elapsed(start, end):
    a, b = epoch(start), epoch(end)
    return max(0.0, b - a) if a is not None and b is not None else None


def begin(group_name):
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        key = "instance_sequence:" + group_name
        row = c.execute("SELECT value FROM controller_settings WHERE key=?", (key,)).fetchone()
        version = int(row["value"]) + 1 if row else 1
        c.execute("INSERT INTO controller_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(version)))
    return version, db.utcnow()


def record(data, version, observed_at):
    """Persist one provider observation and fence older, slower responses."""
    group_name = str(data["name"])
    now = time.time()
    worker = _worker_observation(now, bool(data.get("instances")))
    transformed = []
    for raw in data.get("instances") or []:
        item = raw if isinstance(raw, dict) else {}
        instance_id = item.get("id")
        updated_at = item.get("update_time") or observed_at
        progress = normalize_pull_progress(
            item.get("pulling_progress"), unit=item.get("pulling_progress_unit"),
            total=item.get("pulling_progress_total"), source="salad_provider",
            updated_at=updated_at, instance_id=instance_id,
        )
        transformed.append({
            "id": str(instance_id) if instance_id is not None else None,
            "state": item.get("state"),
            "provider_status": item.get("state"),
            "provider_ready": item.get("ready") if isinstance(item.get("ready"), bool) else None,
            "pull_progress": progress,
            "last_updated_at": updated_at,
        })

    ready, readiness_reason = _readiness(data, transformed, worker)
    phase = _phase(data.get("status"), transformed, worker, ready == "ready", data.get("pending_change"))
    rate = _rate_config()
    result = {
        "queue_mode": data.get("queue_mode"), "auto_gpu_control": data.get("auto_gpu_control"),
        "hold": data.get("hold"), "name": group_name, "group_name": group_name,
        "status": data.get("status"), "provider_status": data.get("status"),
        "pending_change": bool(data.get("pending_change")),
        "desired_replicas": data.get("replicas"), "replicas": data.get("replicas"),
        "observed_instances": len(transformed), "counts": data.get("counts") or {},
        "autoscaler_enabled": bool(data.get("autoscaler_enabled")),
        "min_replicas": data.get("min_replicas"), "max_replicas": data.get("max_replicas"),
        "keep_warm": bool(data.get("keep_warm")), "instances": transformed,
        "worker_status": worker["status"], "worker": worker,
        "last_heartbeat_at": worker["last_heartbeat_at"],
        "readiness": ready, "readiness_reason": readiness_reason,
        "model_readiness": "unknown",
        "model_readiness_reason": "The selected model is not verified by the provider or Worker status endpoint",
        "phase": phase, "phase_label": PHASE_LABELS.get(phase, PHASE_LABELS["unknown"]),
        "phase_started_at": observed_at, "last_updated_at": observed_at,
        "version": version, "version_source": "controller_observation",
        "freshness": {"source": "controller_observation", "stale_after_seconds": 30},
        "financial": {
            "hourly_rate": rate["hourly_rate"] if rate else None,
            "currency": rate["currency"] if rate else None,
            "rate_source": rate["source"] if rate else None,
            "rate_updated_at": observed_at if rate else None,
            "estimated_cost": None, "estimated_cost_currency": None,
            "estimated_cost_by_currency": {}, "estimate_scope": None,
            "estimate_source": "controller-observed instance intervals and operator-configured rate",
            "estimated_cost_updated_at": observed_at,
            "balance": None, "balance_currency": None, "balance_updated_at": None,
            "balance_source": None, "billing": None, "billing_source": None,
            "limitation": "Salad's documented Public API has no account-balance or billing endpoint; actual charges are not available here",
        },
    }

    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        previous = c.execute("SELECT version,snapshot_json FROM instance_observations WHERE group_name=?", (group_name,)).fetchone()
        if previous and previous["version"] >= version:
            return json.loads(previous["snapshot_json"])
        try:
            previous_snapshot = json.loads(previous["snapshot_json"]) if previous else {}
        except (TypeError, ValueError):
            previous_snapshot = {}
        previous_instances = {str(item.get("id")): item for item in previous_snapshot.get("instances", []) if item.get("id")}

        # Session history begins at first controller observation. It is not a
        # claim about Salad's billing boundary or the exact allocation start.
        current_ids = {str(item["id"]) for item in transformed if item.get("id")}
        active_sessions = c.execute("SELECT * FROM instance_sessions WHERE group_name=? AND stopped_at IS NULL", (group_name,)).fetchall()
        session_by_instance = {}
        observed_epoch = epoch(observed_at) or now
        for session_row in active_sessions:
            session = dict(session_row)
            if session["instance_id"] not in current_ids:
                try:
                    intervals = json.loads(session["intervals_json"])
                except (TypeError, ValueError):
                    intervals = []
                if intervals and intervals[-1].get("stopped_at") is None:
                    intervals[-1]["stopped_at"] = observed_at
                c.execute("UPDATE instance_sessions SET stopped_at=?,last_observed_at=?,intervals_json=? WHERE session_id=?",
                          (observed_at, observed_at, json.dumps(intervals), session["session_id"]))
                _close_open_rates(c, session["session_id"], observed_at)
            else:
                session_by_instance[session["instance_id"]] = session
                current_ids.remove(session["instance_id"])

        for instance_id in sorted(current_ids):
            interval = {"started_at": observed_at, "last_observed_at": observed_at,
                        "stopped_at": None, "source": "controller_observation"}
            session_id = str(uuid4())
            c.execute("INSERT INTO instance_sessions(session_id,group_name,instance_id,started_at,last_observed_at,intervals_json) VALUES (?,?,?,?,?,?)",
                      (session_id, group_name, instance_id, observed_at, observed_at, json.dumps([interval])))
            session_by_instance[instance_id] = {
                "session_id": session_id, "group_name": group_name, "instance_id": instance_id,
                "started_at": observed_at, "first_ready_at": None, "stopped_at": None,
                "last_observed_at": observed_at, "intervals_json": json.dumps([interval]),
            }

        current_item_by_id = {str(item["id"]): item for item in transformed if item.get("id")}
        for instance_id, item in current_item_by_id.items():
            old_item = previous_instances.get(instance_id) or {}
            item_phase = phase if ready == "ready" else _phase(
                data.get("status"), [item], worker, False, data.get("pending_change"))
            old_phase = old_item.get("phase")
            item["phase"] = item_phase
            item["phase_label"] = PHASE_LABELS.get(item_phase, PHASE_LABELS["unknown"])
            item["phase_started_at"] = (old_item.get("phase_started_at") if old_phase == item_phase
                                         else observed_at)
            session = session_by_instance[instance_id]
            item["session_id"] = session["session_id"]
            is_ready = ready == "ready"
            if is_ready:
                c.execute("UPDATE instance_sessions SET first_ready_at=COALESCE(first_ready_at,?),last_observed_at=? WHERE session_id=?",
                          (observed_at, observed_at, session["session_id"]))
            else:
                c.execute("UPDATE instance_sessions SET last_observed_at=? WHERE session_id=?",
                          (observed_at, session["session_id"]))
            _open_or_rotate_rate(c, session, rate, observed_at)
            if old_phase != item_phase:
                c.execute("INSERT INTO instance_stage_events(event_id,group_name,instance_id,stage,provider_status,source,observed_at) VALUES (?,?,?,?,?,?,?)",
                          (str(uuid4()), group_name, instance_id, item_phase,
                           str(item.get("provider_status") or "")[:80], "provider_and_controller_observation", observed_at))

        operation = _operation_target(c, group_name, data, observed_at, len(transformed))
        result["operation"] = operation
        if operation and operation["status"] in {"requested", "awaiting_confirmation", "unconfirmed"}:
            result["pending_operation"] = operation
            phase = "operation_pending"
            result["phase"] = phase
            result["phase_label"] = PHASE_LABELS[phase]
            result["phase_started_at"] = operation.get("requested_at") or observed_at
        elif data.get("pending_change"):
            result["pending_operation"] = {"action": "provider_change", "status": "awaiting_provider"}
        else:
            result["pending_operation"] = None

        old_group_phase = previous_snapshot.get("phase")
        if old_group_phase != phase:
            c.execute("INSERT INTO instance_stage_events(event_id,group_name,instance_id,stage,provider_status,source,observed_at) VALUES (?,?,?,?,?,?,?)",
                      (str(uuid4()), group_name, None, phase, str(data.get("status") or "")[:80],
                       "provider_and_controller_observation", observed_at))
        if (operation and operation["status"] in {"requested", "awaiting_confirmation", "unconfirmed"}
                and old_group_phase != phase):
            result["phase_started_at"] = operation.get("requested_at") or observed_at
        else:
            result["phase_started_at"] = (previous_snapshot.get("phase_started_at") if old_group_phase == phase
                                           else observed_at)

        result["phase_timeline"] = [dict(row) for row in c.execute(
            "SELECT event_id,instance_id,stage,provider_status,source,observed_at FROM instance_stage_events "
            "WHERE group_name=? ORDER BY observed_at DESC LIMIT 30", (group_name,))][::-1]

        now_epoch = observed_epoch
        sessions = []
        for row in c.execute("SELECT * FROM instance_sessions WHERE group_name=? ORDER BY started_at DESC LIMIT 100", (group_name,)):
            session = dict(row)
            try:
                session["activity_intervals"] = json.loads(session.pop("intervals_json"))
            except (TypeError, ValueError):
                session["activity_intervals"] = []
            session["source"] = "controller_observation"
            session["billing_boundaries_known"] = False
            session["timing_source"] = "provider_poll_observation"
            finish = session.get("stopped_at") or observed_at
            session["duration_seconds"] = _elapsed(session.get("started_at"), finish)
            session["ready_duration_seconds"] = _elapsed(session.get("first_ready_at"), finish) if session.get("first_ready_at") else None
            session["estimated_cost_by_currency"] = _session_cost(c, session["session_id"], now_epoch)
            sessions.append(session)
        result["sessions"] = sessions
        by_session = {session["session_id"]: session for session in sessions}
        for item in transformed:
            session = by_session.get(item.get("session_id"))
            if session:
                item["session_duration_seconds"] = session["duration_seconds"]
                item["ready_duration_seconds"] = session["ready_duration_seconds"]
                item["session_started_at"] = session["started_at"]

        selected_sessions = [session for session in sessions if session.get("stopped_at") is None]
        scope = "active_sessions"
        if not selected_sessions and sessions:
            selected_sessions = sessions[:1]
            scope = "latest_observed_session"
        cost_breakdown = {}
        for session in selected_sessions:
            for currency, amount in (session.get("estimated_cost_by_currency") or {}).items():
                cost_breakdown[currency] = cost_breakdown.get(currency, 0.0) + amount
        result["financial"]["estimated_cost_by_currency"] = {k: round(v, 6) for k, v in cost_breakdown.items()}
        result["financial"]["estimate_scope"] = scope if selected_sessions else None
        if len(cost_breakdown) == 1:
            currency, amount = next(iter(cost_breakdown.items()))
            result["financial"]["estimated_cost"] = round(amount, 6)
            result["financial"]["estimated_cost_currency"] = currency
        elif len(cost_breakdown) > 1:
            result["financial"]["limitation"] += "; multiple currencies are shown separately and are not combined"

        result["job_activity"] = db.activity_counts(c)
        result["operations"] = [dict(row) for row in c.execute(
            "SELECT operation_id,action,source,status,requested_at,provider_response_at,confirmed_at,safe_detail "
            "FROM instance_operations WHERE group_name=? ORDER BY requested_at DESC LIMIT 20", (group_name,))]
        c.execute("INSERT INTO instance_observations(group_name,version,updated_at,snapshot_json) VALUES (?,?,?,?) "
                  "ON CONFLICT(group_name) DO UPDATE SET version=excluded.version,updated_at=excluded.updated_at,snapshot_json=excluded.snapshot_json",
                  (group_name, version, observed_at, json.dumps(result)))
    return result
