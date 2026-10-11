"""Additive Phase11 observations, intentionally NOT mounted at startup."""
from __future__ import annotations
import hashlib,sqlite3
from datetime import datetime,timezone
REVISION='011_worker_runtime_observations'
DDL=('''CREATE TABLE IF NOT EXISTS worker_v11_observations (
 id TEXT PRIMARY KEY,worker_id TEXT NOT NULL,generation TEXT NOT NULL,
 image_digest TEXT NOT NULL,deployment_revision_id TEXT NOT NULL,
 api_ready INTEGER NOT NULL CHECK(api_ready IN (0,1)),
 models_json TEXT NOT NULL,loras_json TEXT NOT NULL,nodes_json TEXT NOT NULL,
 observed_at TEXT NOT NULL)''',
 '''CREATE INDEX IF NOT EXISTS idx_worker_v11_seen ON worker_v11_observations(worker_id,observed_at DESC)''',
 '''CREATE TRIGGER IF NOT EXISTS worker_v11_no_update BEFORE UPDATE ON worker_v11_observations BEGIN SELECT RAISE(ABORT,'observation history immutable'); END''',
 '''CREATE TRIGGER IF NOT EXISTS worker_v11_no_delete BEFORE DELETE ON worker_v11_observations BEGIN SELECT RAISE(ABORT,'observation history immutable'); END''',
 '''CREATE TABLE IF NOT EXISTS worker_v11_attempts (job_id TEXT NOT NULL REFERENCES jobs(id),
 attempt_id TEXT PRIMARY KEY REFERENCES job_attempts(id),lease_hash TEXT NOT NULL,image_digest TEXT NOT NULL,
 graph_hash TEXT NOT NULL,deadline REAL NOT NULL,state TEXT NOT NULL CHECK(state IN
 ('running','cancel_requested','cancelled','succeeded','superseded')),last_sequence INTEGER NOT NULL DEFAULT 0,
 result_hash TEXT)''',
 '''CREATE INDEX IF NOT EXISTS idx_worker_v11_attempts_job ON worker_v11_attempts(job_id,state)''',
 '''CREATE TABLE IF NOT EXISTS worker_v11_verified_outputs (job_id TEXT NOT NULL,
 attempt_id TEXT NOT NULL REFERENCES worker_v11_attempts(attempt_id),storage_key TEXT UNIQUE NOT NULL,
 sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL CHECK(size_bytes>0),
 PRIMARY KEY(attempt_id,storage_key))''')
CHECKSUM=hashlib.sha256('\n'.join(DDL).encode()).hexdigest()

def migrate(conn:sqlite3.Connection):
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('BEGIN IMMEDIATE')
    try:
        names={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'jobs','job_attempts','schema_migrations'}<=names:raise RuntimeError('Phase01/03/09 migrations and verified owner backfill required')
        row=conn.execute('SELECT checksum FROM schema_migrations WHERE revision=?',(REVISION,)).fetchone()
        if row:
            if row[0]!=CHECKSUM:raise RuntimeError('Phase11 schema checksum mismatch')
            conn.commit();return False
        for sql in DDL:conn.execute(sql)
        conn.execute('INSERT INTO schema_migrations(revision,applied_at,checksum) VALUES(?,?,?)',
                     (REVISION,datetime.now(timezone.utc).isoformat(),CHECKSUM))
        conn.commit();return True
    except BaseException:
        conn.rollback();raise
