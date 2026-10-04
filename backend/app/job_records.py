"""PDF-44/46/47 additive SQLite records and guarded, versioned transitions."""
import json
from uuid import uuid4
from datetime import datetime, timezone

from .contracts import ContractError

STATUS = {"pending": "queued", "submitting": "accepted", "processing": "running",
          "waiting": "queued", "submit_failed": "failed"}
TERMINAL = {"succeeded", "failed", "cancelled", "submit_failed"}
ACTIVE = {"running", "finalizing", "cancel_requested"}
TRANSITIONS = {
    "accepted": {"queued", "pending", "failed", "cancelled"},
    "submitting": {"pending", "queued", "waiting", "preparing", "processing", "running", "finalizing", "succeeded", "failed", "cancelled", "submit_failed", "stalled"},
    "pending": {"queued", "waiting", "preparing", "processing", "running", "finalizing", "succeeded", "failed", "cancelled", "stalled"},
    "queued": {"pending", "waiting", "preparing", "processing", "running", "finalizing", "succeeded", "failed", "cancelled", "stalled"},
    "waiting": {"pending", "queued", "preparing", "processing", "running", "finalizing", "succeeded", "failed", "cancelled", "stalled"},
    "preparing": {"processing", "running", "finalizing", "succeeded", "failed", "cancel_requested", "cancelled", "stalled"},
    "processing": {"running", "finalizing", "succeeded", "failed", "cancel_requested", "cancelled", "stalled"},
    "running": {"finalizing", "succeeded", "failed", "cancel_requested", "cancelled", "stalled"},
    "finalizing": {"succeeded", "failed", "cancel_requested", "cancelled"},
    "cancel_requested": {"finalizing", "cancelled", "succeeded", "failed", "stalled"},
    # Legacy 'stalled' is an overdue communication observation, not a failure.
    "stalled": {"pending", "queued", "waiting", "preparing", "processing", "running", "finalizing", "succeeded", "failed", "cancelled"},
}


def migrate(c):
    cols = {r["name"] for r in c.execute("PRAGMA table_info(jobs)")}
    additions = {"client_request_id": "TEXT", "request_hash": "TEXT", "snapshot_json": "TEXT",
                 "owner": "TEXT", "source_job_id": "TEXT", "queued_at": "TEXT", "started_at": "TEXT",
                 "finished_at": "TEXT", "active_attempt_id": "TEXT", "version": "INTEGER NOT NULL DEFAULT 1",
                 "retry_generation": "INTEGER NOT NULL DEFAULT 0"}
    for name, ddl in additions.items():
        if name not in cols:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")
    c.executescript("""
      CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_client_request ON jobs(client_request_id)
        WHERE client_request_id IS NOT NULL;
      CREATE TABLE IF NOT EXISTS job_attempts (
        id TEXT PRIMARY KEY, job_id TEXT NOT NULL, sequence INTEGER NOT NULL,
        previous_attempt_id TEXT, worker_id TEXT, lease_token_hash TEXT,
        provider_job_id TEXT, output_prefix TEXT,
        created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, state TEXT NOT NULL,
        failure_reason TEXT, result_hash TEXT, UNIQUE(job_id,sequence)
      );
      CREATE TABLE IF NOT EXISTS job_assets (
        asset_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, attempt_id TEXT,
        storage_key TEXT NOT NULL, media_type TEXT, mime_type TEXT,
        width INTEGER, height INTEGER, size_bytes INTEGER, duration_seconds REAL,
        frame_rate REAL, status TEXT NOT NULL, verified_at TEXT, error_code TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(job_id,storage_key)
      );
      CREATE INDEX IF NOT EXISTS idx_job_assets_storage_key ON job_assets(storage_key,status);
      CREATE TABLE IF NOT EXISTS input_assets (
        asset_id TEXT PRIMARY KEY, storage_key TEXT NOT NULL UNIQUE,
        mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
        width INTEGER NOT NULL, height INTEGER NOT NULL, created_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS job_events (
        job_id TEXT NOT NULL, version INTEGER NOT NULL, attempt_id TEXT,
        previous_state TEXT, state TEXT NOT NULL, reason TEXT, observed_at TEXT NOT NULL,
        PRIMARY KEY(job_id,version)
      );
      CREATE TABLE IF NOT EXISTS job_progress (
        job_id TEXT NOT NULL, attempt_id TEXT NOT NULL, sequence INTEGER NOT NULL,
        phase TEXT NOT NULL, label TEXT NOT NULL, value REAL, total REAL,
        unit TEXT, scope TEXT NOT NULL, source TEXT NOT NULL, observed_at TEXT NOT NULL,
        PRIMARY KEY(job_id,attempt_id)
      );
      CREATE INDEX IF NOT EXISTS idx_job_progress_attempt ON job_progress(job_id,attempt_id,sequence);
      CREATE TABLE IF NOT EXISTS job_progress_events (
        job_id TEXT NOT NULL, attempt_id TEXT NOT NULL, sequence INTEGER NOT NULL,
        phase TEXT NOT NULL, label TEXT NOT NULL, value REAL, total REAL,
        unit TEXT, scope TEXT NOT NULL, source TEXT NOT NULL, observed_at TEXT NOT NULL,
        PRIMARY KEY(job_id,attempt_id,sequence)
      );
      CREATE INDEX IF NOT EXISTS idx_job_progress_events_recent
        ON job_progress_events(job_id,attempt_id,sequence DESC);
      CREATE TABLE IF NOT EXISTS instance_observations (
        group_name TEXT PRIMARY KEY, version INTEGER NOT NULL, updated_at TEXT NOT NULL,
        snapshot_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS instance_sessions (
        session_id TEXT PRIMARY KEY, group_name TEXT NOT NULL, instance_id TEXT NOT NULL,
        started_at TEXT NOT NULL, first_ready_at TEXT, stopped_at TEXT,
        last_observed_at TEXT NOT NULL, intervals_json TEXT NOT NULL
      );
      CREATE UNIQUE INDEX IF NOT EXISTS idx_instance_active_session
        ON instance_sessions(group_name,instance_id) WHERE stopped_at IS NULL;
      CREATE TABLE IF NOT EXISTS instance_cost_periods (
        period_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, group_name TEXT NOT NULL,
        instance_id TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
        hourly_rate REAL NOT NULL, currency TEXT NOT NULL, rate_source TEXT NOT NULL,
        rate_observed_at TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_instance_cost_session
        ON instance_cost_periods(session_id,started_at);
      CREATE TABLE IF NOT EXISTS instance_stage_events (
        event_id TEXT PRIMARY KEY, group_name TEXT NOT NULL, instance_id TEXT,
        stage TEXT NOT NULL, provider_status TEXT, source TEXT NOT NULL,
        observed_at TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_instance_stage_events_recent
        ON instance_stage_events(group_name,instance_id,observed_at DESC);
      CREATE TABLE IF NOT EXISTS instance_operations (
        operation_id TEXT PRIMARY KEY, group_name TEXT NOT NULL, action TEXT NOT NULL,
        source TEXT NOT NULL, status TEXT NOT NULL, requested_at TEXT NOT NULL,
        provider_response_at TEXT, confirmed_at TEXT, target_json TEXT,
        safe_detail TEXT
      );
      CREATE INDEX IF NOT EXISTS idx_instance_operations_recent
        ON instance_operations(group_name,requested_at DESC);
      CREATE TRIGGER IF NOT EXISTS jobs_snapshot_immutable
        BEFORE UPDATE OF snapshot_json,request_json,variables_json ON jobs
        WHEN NEW.snapshot_json IS NOT OLD.snapshot_json OR NEW.request_json IS NOT OLD.request_json
          OR NEW.variables_json IS NOT OLD.variables_json
        BEGIN SELECT RAISE(ABORT,'submitted Job snapshot is immutable'); END;
    """)
    allowed = " OR ".join("(OLD.state='" + old + "' AND NEW.state IN (" +
                          ",".join("'" + new + "'" for new in sorted(news)) + "))"
                          for old, news in TRANSITIONS.items())
    # Requeue requires the explicit retry/recovery generation fence. Failed and
    # cancelled can never be reopened by a late provider update.
    retry = "(NEW.retry_generation=OLD.retry_generation+1 AND ((NEW.state='pending' AND OLD.execution_mode='direct' AND OLD.state IN ('failed','cancelled','running','finalizing')) OR (NEW.state='submitting' AND OLD.execution_mode='salad_queue' AND OLD.state IN ('failed','cancelled','submit_failed','stalled'))))"
    c.execute("DROP TRIGGER IF EXISTS jobs_transition_guard")
    c.execute(f"""CREATE TRIGGER jobs_transition_guard BEFORE UPDATE OF state ON jobs
      WHEN NEW.state!=OLD.state AND NOT ({allowed} OR {retry})
      BEGIN SELECT RAISE(ABORT,'invalid Job transition'); END""")
    c.executescript("""
      CREATE TRIGGER IF NOT EXISTS jobs_success_requires_assets BEFORE UPDATE OF state ON jobs
      WHEN NEW.state='succeeded' AND NEW.snapshot_json IS NOT NULL
        AND (OLD.state!='finalizing' OR NOT EXISTS (
          SELECT 1 FROM job_assets WHERE job_id=NEW.id AND status='available' AND attempt_id=NEW.active_attempt_id))
      BEGIN SELECT RAISE(ABORT,'successful Job requires verified output assets'); END;
      CREATE TRIGGER IF NOT EXISTS jobs_insert_event AFTER INSERT ON jobs BEGIN
        INSERT INTO job_events VALUES (NEW.id,NEW.version,NEW.active_attempt_id,NULL,NEW.state,NULL,NEW.created_at);
      END;
      CREATE TRIGGER IF NOT EXISTS jobs_record_version
      AFTER UPDATE OF state,output_json,error_text,salad_job_id,hidden,active_attempt_id,last_heartbeat ON jobs
      BEGIN
        UPDATE jobs SET version=OLD.version+1 WHERE id=NEW.id;
        INSERT INTO job_events VALUES (NEW.id,OLD.version+1,NEW.active_attempt_id,OLD.state,NEW.state,NEW.error_text,NEW.updated_at);
      END;
    """)


def acceptance(c, local_id, client_request_id, request_hash):
    if not client_request_id:
        return None
    row = c.execute("SELECT id,request_hash,hidden FROM jobs WHERE client_request_id=?", (client_request_id,)).fetchone()
    if not row:
        return None
    if row["request_hash"] != request_hash:
        raise ContractError("idempotency_conflict", "This request key already belongs to different inputs", "client_request_id", 409)
    if row["hidden"]:
        raise ContractError("request_hidden", "The accepted Job was hidden; it cannot be resubmitted with this key", "client_request_id", 409)
    return row["id"]


def start_attempt(c, row, worker_id, token_hash, now):
    previous = c.execute("SELECT id,sequence FROM job_attempts WHERE job_id=? ORDER BY sequence DESC LIMIT 1", (row["id"],)).fetchone()
    attempt_id = str(uuid4())
    sequence = previous["sequence"] + 1 if previous else max(1, row["attempts"] + 1)
    c.execute("INSERT INTO job_attempts(id,job_id,sequence,previous_attempt_id,worker_id,lease_token_hash,created_at,started_at,state) VALUES (?,?,?,?,?,?,?,?,?)",
              (attempt_id, row["id"], sequence, previous["id"] if previous else None, worker_id, token_hash, now, now, "running"))
    return attempt_id


def provider_attempt(c, job_id, output_prefix=None):
    from .db import utcnow
    previous = c.execute("SELECT id,sequence FROM job_attempts WHERE job_id=? ORDER BY sequence DESC LIMIT 1", (job_id,)).fetchone()
    attempt_id = str(uuid4())
    c.execute("INSERT INTO job_attempts(id,job_id,sequence,previous_attempt_id,created_at,state,output_prefix) VALUES (?,?,?,?,?,'submitting',?)", (attempt_id, job_id, previous["sequence"] + 1 if previous else 1, previous["id"] if previous else None, utcnow(), output_prefix or f"outputs/{job_id}/{attempt_id}/"))
    return attempt_id


def save_assets(c, assets):
    for asset in assets:
        fields = list(asset)
        c.execute("INSERT INTO job_assets(" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ") ON CONFLICT(job_id,storage_key) DO NOTHING", list(asset.values()))


def asset_for_storage_key(c, storage_key):
    row = c.execute("SELECT * FROM job_assets WHERE storage_key=? AND status='available' ORDER BY created_at DESC LIMIT 1",
                    (storage_key,)).fetchone()
    return dict(row) if row else None


def end_attempt(c, attempt_id, state, now, reason=None, result_hash=None):
    if attempt_id:
        c.execute("UPDATE job_attempts SET state=?,finished_at=?,failure_reason=?,result_hash=? WHERE id=? AND finished_at IS NULL",
                  (state, now, reason, result_hash, attempt_id))


def enrich(c, item, *, include_progress_history=False):
    raw = item.pop("snapshot_json", None)
    item["snapshot"] = json.loads(raw) if raw else None
    item["job_id"] = item["id"]
    item["status"] = STATUS.get(item["state"], item["state"])
    item["error_summary"] = item.get("error_text")
    attempts = [dict(r) for r in c.execute(
        "SELECT id,job_id,sequence,previous_attempt_id,worker_id,provider_job_id,created_at,started_at,finished_at,state,failure_reason FROM job_attempts WHERE job_id=? ORDER BY sequence", (item["id"],))]
    progress_by_attempt = {r["attempt_id"]: dict(r) for r in c.execute(
        "SELECT * FROM job_progress WHERE job_id=?", (item["id"],))}
    for attempt in attempts:
        attempt["progress"] = progress_by_attempt.get(attempt["id"])
        attempt["timing"] = attempt_timing(attempt, item.get("state"), item.get("active_attempt_id"))
    item["attempt_history"] = attempts
    item["assets"] = [dict(r) for r in c.execute("SELECT * FROM job_assets WHERE job_id=? ORDER BY asset_id", (item["id"],))]
    item["timeline"] = [dict(r) for r in c.execute("SELECT * FROM job_events WHERE job_id=? AND (previous_state IS NULL OR state!=previous_state) ORDER BY version", (item["id"],))]
    item["progress"] = progress_by_attempt.get(item.get("active_attempt_id"))
    item["progress_history"] = []
    if include_progress_history and item.get("active_attempt_id"):
        item["progress_history"] = [dict(r) for r in c.execute(
            "SELECT * FROM (SELECT * FROM job_progress_events WHERE job_id=? AND attempt_id=? ORDER BY sequence DESC LIMIT 50) ORDER BY sequence",
            (item["id"], item["active_attempt_id"]))]
    item["timing"] = job_timing(item, attempts)
    return item


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _seconds(start, end):
    a, b = _parse_time(start), _parse_time(end)
    return max(0.0, (b - a).total_seconds()) if a and b else None


def attempt_timing(attempt, job_state=None, active_attempt_id=None):
    end = attempt.get("finished_at")
    if not end and attempt.get("id") == active_attempt_id and job_state in ACTIVE:
        end = datetime.now(timezone.utc).isoformat()
    return {
        "queue_wait_seconds": _seconds(attempt.get("created_at"), attempt.get("started_at")),
        "worker_seconds": _seconds(attempt.get("started_at"), end),
    }


def job_timing(item, attempts):
    created = item.get("created_at")
    first_start = next((a.get("started_at") for a in attempts if a.get("started_at")), None)
    active = item.get("state") in ACTIVE or item.get("state") in {"pending", "submitting", "queued", "waiting", "preparing", "processing"}
    now = datetime.now(timezone.utc).isoformat()
    queue_end = first_start or (now if active else None)
    total_end = item.get("finished_at") or (now if active else None)
    durations = [a.get("timing", {}).get("worker_seconds") for a in attempts]
    waits = [a.get("timing", {}).get("queue_wait_seconds") for a in attempts]
    return {
        "created_at": created,
        "queued_at": item.get("queued_at"),
        "started_at": item.get("started_at"),
        "finished_at": item.get("finished_at"),
        "first_queue_wait_seconds": _seconds(created, queue_end),
        "worker_seconds": round(sum(value for value in durations if value is not None), 3) if any(value is not None for value in durations) else None,
        "total_seconds": _seconds(created, total_end),
        "attempt_wait_seconds": round(sum(value for value in waits if value is not None), 3) if any(value is not None for value in waits) else None,
    }
