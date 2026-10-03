import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
from .config import settings


def utcnow():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    p = Path(settings.db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            api_prompt TEXT NOT NULL,
            ui_workflow TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            salad_job_id TEXT,
            workflow_id TEXT,
            state TEXT NOT NULL,
            request_json TEXT NOT NULL,
            output_json TEXT,
            error_text TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(workflow_id) REFERENCES workflows(id)
        );
        """)

        c.execute("""CREATE TABLE IF NOT EXISTS controller_settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        )""")

        cols = {row["name"] for row in c.execute("PRAGMA table_info(jobs)").fetchall()}

        if "priority" not in cols:
            # Priority for historic rows is read from the currently configured .env.
            c.execute(
                f"ALTER TABLE jobs ADD COLUMN priority TEXT NOT NULL DEFAULT '{settings.salad_priority}'"
            )

        if "variables_json" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN variables_json TEXT")
        if "hidden" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")

        if "salad_queue" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN salad_queue TEXT")

        c.execute(
            """UPDATE jobs
               SET salad_queue=?
               WHERE salad_queue IS NULL OR salad_queue=''""",
            (settings.salad_legacy_queue,),
        )

        # Direct queue migration is additive: existing Salad Queue jobs retain
        # their original execution_mode and can still be inspected/retried.
        direct_columns = {
            "execution_mode": "TEXT NOT NULL DEFAULT 'salad_queue'",
            "attempts": "INTEGER NOT NULL DEFAULT 0",
            "lease_token_hash": "TEXT",
            "worker_id": "TEXT",
            "lease_deadline": "REAL",
            "last_heartbeat": "REAL",
            "next_attempt_at": "REAL NOT NULL DEFAULT 0",
        }
        for name, ddl in direct_columns.items():
            if name not in cols:
                c.execute(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")
        c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_direct_queue "
                  "ON jobs(execution_mode,state,next_attempt_at,created_at)")


def list_workflows():
    with connect() as c:
        rows = c.execute(
            "SELECT id,name,created_at,updated_at FROM workflows ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_workflow(workflow_id):
    with connect() as c:
        row = c.execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["api_prompt"] = json.loads(d["api_prompt"])
        d["ui_workflow"] = json.loads(d["ui_workflow"]) if d["ui_workflow"] else None
        return d


def save_workflow(workflow_id, name, api_prompt, ui_workflow=None):
    now = utcnow()
    api_json = json.dumps(api_prompt, separators=(",", ":"))
    ui_json = json.dumps(ui_workflow, separators=(",", ":")) if ui_workflow is not None else None
    with connect() as c:
        exists = c.execute("SELECT 1 FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        if exists:
            c.execute(
                """UPDATE workflows
                   SET name=?, api_prompt=?, ui_workflow=?, updated_at=?
                   WHERE id=?""",
                (name, api_json, ui_json, now, workflow_id),
            )
        else:
            c.execute(
                """INSERT INTO workflows
                   (id,name,api_prompt,ui_workflow,created_at,updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (workflow_id, name, api_json, ui_json, now, now),
            )
    return get_workflow(workflow_id)


def delete_workflow(workflow_id):
    with connect() as c:
        c.execute("DELETE FROM workflows WHERE id=?", (workflow_id,))


def create_job(local_id, workflow_id, request_payload, *, priority=None, salad_queue=None, variables=None, execution_mode="salad_queue"):
    priority = priority or settings.salad_priority
    now = utcnow()
    with connect() as c:
        c.execute(
            """INSERT INTO jobs
               (id,salad_job_id,workflow_id,state,request_json,
                priority,salad_queue,variables_json,created_at,updated_at,execution_mode)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                local_id, None, workflow_id,
                "pending" if execution_mode == "direct" else "submitting",
                json.dumps(request_payload, separators=(",", ":")),
                priority, salad_queue,
                json.dumps(variables, separators=(",", ":")) if variables is not None else None,
                now, now, execution_mode,
            ),
        )


def update_job(local_id, *, salad_job_id=None, state=None, output=None, error=None):
    fields = ["updated_at=?"]
    values = [utcnow()]
    if salad_job_id is not None:
        fields.append("salad_job_id=?")
        values.append(salad_job_id)
    if state is not None:
        fields.append("state=?")
        values.append(state)
    if output is not None:
        fields.append("output_json=?")
        values.append(json.dumps(output, separators=(",", ":")))
    if error is not None:
        fields.append("error_text=?")
        values.append(error)
    values.append(local_id)
    with connect() as c:
        c.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=?", values)


def get_job(local_id):
    with connect() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (local_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["request"] = json.loads(d.pop("request_json"))
        raw = d.pop("output_json")
        d["output"] = json.loads(raw) if raw else None
        var_raw = d.pop("variables_json", None)
        d["variables"] = json.loads(var_raw) if var_raw else None
        return d


def list_jobs(limit=50):
    limit = max(1, min(int(limit), 200))
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM jobs WHERE hidden=0 ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["request"] = json.loads(d.pop("request_json"))
        raw = d.pop("output_json")
        d["output"] = json.loads(raw) if raw else None
        var_raw = d.pop("variables_json", None)
        d["variables"] = json.loads(var_raw) if var_raw else None
        result.append(d)
    return result


def hide_job(local_id):
    with connect() as c:
        cursor = c.execute(
            "UPDATE jobs SET hidden=1, updated_at=? WHERE id=? AND hidden=0",
            (utcnow(), local_id),
        )
        return cursor.rowcount > 0


def mark_stalled(local_id, minutes):
    from .job_lifecycle import stale_message
    with connect() as c:
        c.execute(
            """UPDATE jobs SET state='stalled', error_text=?, updated_at=?
               WHERE id=? AND state IN ('pending','submitting','queued','waiting','processing','running')""",
            (stale_message(minutes), utcnow(), local_id),
        )
