"""Durable, single-GPU pull queue. No Salad IMDS/Job Queue dependency.

The controller uses SQLite transactions for exclusive leases. A lease only
protects dispatch; like every distributed queue this is at-least-once after a
network partition. Result writes are idempotent and fenced by the lease token.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from uuid import uuid4

from . import db, storage, job_records
from .contracts import digest

DIRECT_MODE = "direct"


def enabled() -> bool:
    return os.getenv("DIRECT_QUEUE_ENABLED", "false").lower() == "true"


def require_enabled():
    if not enabled():
        raise ValueError("DIRECT_QUEUE_ENABLED=true is required")


def integer(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    return value


def lease_seconds() -> int:
    return integer("DIRECT_LEASE_SECONDS", 120, 45, 3600)


def max_attempts() -> int:
    return integer("DIRECT_MAX_ATTEMPTS", 3, 1, 10)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _time() -> float:
    return time.time()


def _now() -> str:
    return db.utcnow()


def save_setting(key: str, value):
    with db.connect() as c:
        c.execute(
            "INSERT INTO controller_settings(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )


def load_setting(key: str, default=None):
    with db.connect() as c:
        row = c.execute("SELECT value FROM controller_settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def counters() -> dict:
    with db.connect() as c:
        rows = c.execute(
            "SELECT state,COUNT(*) n FROM jobs WHERE execution_mode=? "
            "GROUP BY state", (DIRECT_MODE,),
        ).fetchall()
    result = {"pending": 0, "running": 0, "failed": 0, "succeeded": 0}
    result.update({r["state"]: r["n"] for r in rows})
    # Finalizing still owns the single GPU lease and blocks dispatch/stop.
    result["running"] += result.get("finalizing", 0)
    return result


def _recover_expired(c, now: float):
    rows = c.execute(
        "SELECT id,attempts,active_attempt_id FROM jobs WHERE execution_mode=? AND state IN ('running','finalizing') "
        "AND lease_deadline IS NOT NULL AND lease_deadline < ?",
        (DIRECT_MODE, now),
    ).fetchall()
    for row in rows:
        exhausted = row["attempts"] >= max_attempts()
        observed = _now()
        reason = "Worker heartbeat expired; retry limit reached" if exhausted else "Worker heartbeat expired; scheduled for retry"
        job_records.end_attempt(c, row["active_attempt_id"], "expired", observed, reason)
        c.execute(
            """UPDATE jobs SET state=?,lease_token_hash=NULL,worker_id=NULL,
               lease_deadline=NULL,last_heartbeat=NULL,next_attempt_at=?,
               error_text=?,updated_at=?,finished_at=?,active_attempt_id=NULL,
               retry_generation=retry_generation+1 WHERE id=? AND state IN ('running','finalizing')""",
            (
                "failed" if exhausted else "pending",
                now + min(180, 15 * 2 ** row["attempts"]),
                reason, observed, observed if exhausted else None, row["id"],
            ),
        )
    return len(rows)


def recover_expired() -> int:
    require_enabled()
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        return _recover_expired(c, _time())


def claim(worker_id: str) -> dict | None:
    require_enabled()
    if not worker_id or len(worker_id) > 128:
        raise ValueError("invalid worker ID")
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        now = _time()
        _recover_expired(c, now)
        # At most one *active* direct job, even if multiple workers race.
        if c.execute("SELECT 1 FROM jobs WHERE execution_mode=? AND state IN ('running','finalizing') LIMIT 1",
                     (DIRECT_MODE,)).fetchone():
            return None
        row = c.execute(
            """SELECT * FROM jobs WHERE execution_mode=? AND state='pending'
               AND next_attempt_at<=? ORDER BY
                 CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1
                 WHEN 'low' THEN 2 ELSE 3 END,
                 created_at ASC LIMIT 1""", (DIRECT_MODE, now),
        ).fetchone()
        if not row:
            return None
        token = uuid4().hex + uuid4().hex
        observed = _now()
        attempt_id = job_records.start_attempt(c, row, worker_id, _digest(token), observed)
        c.execute(
            """UPDATE jobs SET state='running',attempts=attempts+1,
               lease_token_hash=?,worker_id=?,lease_deadline=?,last_heartbeat=?,
               error_text=NULL,updated_at=?,active_attempt_id=?,started_at=COALESCE(started_at,?),
               finished_at=NULL WHERE id=?""",
            (_digest(token), worker_id, now + lease_seconds(), now, observed, attempt_id, observed, row["id"]),
        )
        payload = json.loads(row["request_json"])
        # Re-sign input URLs at dispatch, not at submission. Durable s3://
        # references survive long GPU cold starts and queueing delays.
        payload = storage.sign_s3_values(payload)
        if row["snapshot_json"] and isinstance(payload.get("s3"), dict):
            payload["s3"]["prefix"] = f"outputs/{row['id']}/{attempt_id}/"
        return {"job_id": row["id"], "attempt": row["attempts"] + 1,
                "attempt_id": attempt_id, "lease_token": token, "request": payload}


def _fenced(c, job_id: str, token: str, attempt_id=None):
    if not token or len(token) > 256:
        return None
    row = c.execute(
        """SELECT * FROM jobs WHERE id=? AND execution_mode=?
           AND state IN ('running','finalizing') AND lease_token_hash=?""",
        (job_id, DIRECT_MODE, _digest(token)),
    ).fetchone()
    return row if row and float(row["lease_deadline"] or 0) >= _time() and (attempt_id is None or attempt_id == row["active_attempt_id"]) else None


def heartbeat(job_id: str, token: str, attempt_id=None) -> bool:
    require_enabled()
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        if not _fenced(c, job_id, token, attempt_id):
            return False
        now = _time()
        c.execute(
            "UPDATE jobs SET lease_deadline=?,last_heartbeat=?,updated_at=? WHERE id=?",
            (now + lease_seconds(), now, _now(), job_id),
        )
    return True


def finish(job_id: str, token: str, output: dict, attempt_id=None) -> bool:
    require_enabled()
    if not isinstance(output, dict):
        raise ValueError("Job result must be a JSON object")
    result_hash = digest(output)
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = _fenced(c, job_id, token, attempt_id)
        if not row:
            # Identical redelivery is acknowledged without changing anything.
            previous = c.execute("SELECT result_hash FROM job_attempts WHERE job_id=? AND lease_token_hash=? AND state='succeeded' AND (? IS NULL OR id=?)", (job_id, _digest(token), attempt_id, attempt_id)).fetchone()
            return bool(previous and previous["result_hash"] == result_hash)
        if row["state"] == "running":
            c.execute("UPDATE jobs SET state='finalizing',updated_at=? WHERE id=?", (_now(), job_id))
            c.execute("UPDATE job_attempts SET state='finalizing' WHERE id=? AND finished_at IS NULL", (row["active_attempt_id"],))
        active_id = row["active_attempt_id"]
        snapshot = row["snapshot_json"]
    # Historic unversioned direct jobs keep their old result format. New jobs
    # require real files. The finalizing state is visible during R2 validation.
    assets = storage.validate_outputs(job_id, active_id, output) if snapshot else []
    success = not snapshot or any(a["status"] == "available" for a in assets)
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        if not _fenced(c, job_id, token, active_id):
            return False
        job_records.save_assets(c, assets)
        observed = _now()
        state = "succeeded" if success else "failed"
        error = None if success else "No output file could be verified in storage"
        job_records.end_attempt(c, active_id, state, observed, error, result_hash)
        c.execute(
            """UPDATE jobs SET state=?,output_json=?,error_text=?,finished_at=?,
               lease_token_hash=NULL,worker_id=NULL,lease_deadline=NULL,
               updated_at=? WHERE id=?""",
            (state, json.dumps(output, separators=(",", ":")), error, observed, observed, job_id),
        )
    return True


def fail(job_id: str, token: str, message: str, retryable: bool, attempt_id=None) -> bool:
    require_enabled()
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = _fenced(c, job_id, token, attempt_id)
        if not row:
            return False
        can_retry = retryable and row["attempts"] < max_attempts()
        observed = _now()
        job_records.end_attempt(c, row["active_attempt_id"], "failed", observed, str(message)[:600])
        c.execute(
            """UPDATE jobs SET state=?,error_text=?,next_attempt_at=?,
               lease_token_hash=NULL,worker_id=NULL,lease_deadline=NULL,
               last_heartbeat=NULL,updated_at=?,finished_at=?,
               retry_generation=retry_generation+1 WHERE id=?""",
            ("pending" if can_retry else "failed",
             str(message)[:600],
             _time() + min(180, 15 * 2 ** row["attempts"]) if can_retry else 0,
             observed, None if can_retry else observed, job_id),
        )
    return True


def cancel_pending(job_id: str) -> bool:
    require_enabled()
    with db.connect() as c:
        return c.execute(
            """UPDATE jobs SET state='cancelled',updated_at=?,finished_at=? WHERE id=?
               AND execution_mode=? AND state='pending'""",
            (_now(), _now(), job_id, DIRECT_MODE),
        ).rowcount == 1


def retry(job_id: str) -> bool:
    require_enabled()
    with db.connect() as c:
        return c.execute(
            """UPDATE jobs SET state='pending',attempts=0,next_attempt_at=0,
               error_text=NULL,updated_at=?,finished_at=NULL,active_attempt_id=NULL,
               retry_generation=retry_generation+1 WHERE id=?
               AND execution_mode=? AND state IN ('failed','cancelled')""",
            (_now(), job_id, DIRECT_MODE),
        ).rowcount == 1


def worker_seen(worker_id: str):
    require_enabled()
    if not worker_id or len(worker_id) > 128:
        raise ValueError("invalid worker ID")
    save_setting("direct_worker_seen", {"worker_id": worker_id, "at": _time()})
