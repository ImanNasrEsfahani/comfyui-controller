import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone
from .config import settings

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def connect():
    p = Path(settings.db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect() as c:
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

def rowdict(row):
    return dict(row) if row else None

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

def create_job(local_id, workflow_id, request_payload):
    now = utcnow()
    with connect() as c:
        c.execute(
            """INSERT INTO jobs
               (id,salad_job_id,workflow_id,state,request_json,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                local_id,
                None,
                workflow_id,
                "submitting",
                json.dumps(request_payload, separators=(",", ":")),
                now,
                now,
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
        return d

def list_jobs(limit=50):
    limit = max(1, min(int(limit), 200))
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["request"] = json.loads(d.pop("request_json"))
        raw = d.pop("output_json")
        d["output"] = json.loads(raw) if raw else None
        result.append(d)
    return result
