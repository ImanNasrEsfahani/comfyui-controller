"""Conservative GPU controller. One process in Docker Compose, opt-in billing.

A failed cold start latches a HOLD instead of relaunching forever. Control-plane
calls never contain R2 credentials in their logs.
"""
import logging
import os
import time

from . import db, direct_queue as queue, settings_store, salad_control

log = logging.getLogger("direct-scheduler")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def auto_enabled() -> bool:
    return os.getenv("DIRECT_GPU_AUTO_CONTROL", "false").lower() == "true"


def _safe_group():
    current = settings_store.active()
    group = salad_control._get_group(current["group_name"])
    if not group:
        raise RuntimeError("Active Salad group not found")
    if (group.get("container") or {}).get("image") != current["image"]:
        raise RuntimeError("Active group image differs from saved configuration")
    if group.get("queue_connection") or group.get("queue_autoscaler"):
        raise RuntimeError("Active group still uses Salad Job Queue; refusing GPU automation")
    if (group.get("container") or {}).get("command"):
        raise RuntimeError("Group has a custom command override; restore Docker CMD first")
    if group.get("restart_policy") != "never":
        raise RuntimeError("Set restart_policy=never before automated scaling")
    return group


def tick():
    if not queue.enabled():
        return
    recovered = queue.recover_expired()
    if recovered:
        log.warning("Recovered %s expired job lease(s)", recovered)
    if not auto_enabled():
        return
    counts = queue.counters()
    demand = counts["pending"] + counts["running"] > 0 or bool(queue.load_setting("direct_keep_warm", False))
    if queue.load_setting("direct_hold", False):
        # A failed stop is retried, but HOLD must never trigger a replacement.
        group = _safe_group()
        salad_control.status(group_data=group)
        if not group.get("pending_change") and (group.get("current_state") or {}).get("status") != "stopped":
            salad_control.stop(source="scheduler_hold", hold_shutdown=True)
        return
    group = _safe_group()
    # Reconcile any in-flight controller operation from provider observations;
    # scheduler progress must not depend on an open browser dashboard.
    salad_control.status(group_data=group)
    if group.get("pending_change"):
        return
    now = time.time()
    desired = int(group.get("replicas") or 0)
    state = (group.get("current_state") or {}).get("status", "")
    boot_started = float(queue.load_setting("direct_boot_started", 0) or 0)
    seen = queue.load_setting("direct_worker_seen", {}) or {}
    last_seen = float(seen.get("at", 0) or 0)
    # Once a previous worker has started, lack of fresh hello implies that
    # the allocated instance has stopped working. Do not replace it forever.
    timeout = queue.integer("DIRECT_STARTUP_TIMEOUT_SECONDS", 1800, 600, 7200)
    boot_timed_out = demand and desired and boot_started and last_seen < boot_started and now - boot_started > timeout
    worker_disappeared = (demand and desired and boot_started and last_seen >= boot_started
                          and not counts["running"] and now - last_seen > 180)
    if boot_timed_out or worker_disappeared:
        reason = "GPU did not register within startup deadline" if boot_timed_out else "Direct worker heartbeat disappeared"
        queue.save_setting("direct_hold", reason)
        log.error("%s; HOLD activated. Manual reset required", reason)
        if state != "stopped":
            salad_control.stop(source="scheduler_hold", hold_shutdown=True)
        return
    if demand:
        queue.save_setting("direct_last_demand", now)
        if state == "stopped":
            if desired != 0:
                # Group stop does not guarantee its replica target was reset.
                salad_control.set_replicas(0, source="scheduler")
                return
            salad_control.start(source="scheduler")
            log.info("Starting idle Salad container group")
            return
        if desired == 0:
            salad_control.set_replicas(1, source="scheduler")
            queue.save_setting("direct_boot_started", now)
            log.info("Requested exactly one GPU replica")
        return
    # An empty queue is not a reason to kill a running job. Let its lease
    # expire/recover first; all running direct jobs are counted as demand.
    idle = queue.integer("DIRECT_IDLE_SECONDS", 900, 120, 86400)
    last_demand_setting = queue.load_setting("direct_last_demand", None)
    if last_demand_setting is None:
        queue.save_setting("direct_last_demand", now)
        return
    last_demand = float(last_demand_setting)
    if now - last_demand < idle:
        return
    if desired > 0:
        salad_control.set_replicas(0, source="scheduler")
        queue.save_setting("direct_boot_started", 0)
        log.info("Idle timeout; requested zero GPU replicas")
    elif state not in ("stopped", "stopping"):
        salad_control.stop(source="scheduler")
        log.info("Stopped idle Salad container group")


def main():
    db.init_db()
    settings_store.seed()
    interval = queue.integer("DIRECT_POLL_SECONDS", 20, 10, 300)
    log.info("Direct queue scheduler online; automatic GPU control=%s", auto_enabled())
    while True:
        try:
            tick()
        except Exception as exc:
            log.exception("Controller tick failed (%s); will retry without allocating extra GPUs", type(exc).__name__)
        time.sleep(interval)


if __name__ == "__main__":
    main()
