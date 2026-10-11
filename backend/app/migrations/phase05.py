"""Opt-in, additive Phase05 schema. Run explicitly against an offline SQLite copy.

Do not invoke at startup. No production migration or data reattribution.
"""
from __future__ import annotations
import hashlib
import sqlite3
from datetime import datetime,timezone

REVISION = '005_account_admin'
DDL = (
 '''CREATE TABLE IF NOT EXISTS account_email_changes (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 new_email TEXT NOT NULL, new_email_normalized TEXT NOT NULL,
 token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, consumed_at TEXT,
 requested_at TEXT NOT NULL)''',
 '''CREATE INDEX IF NOT EXISTS idx_account_email_changes_user ON account_email_changes(user_id,requested_at)''',
 '''CREATE TABLE IF NOT EXISTS account_data_requests (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),
 request_type TEXT NOT NULL CHECK(request_type IN ('export','delete')),
 status TEXT NOT NULL DEFAULT 'pending_review' CHECK(status IN ('pending_review','blocked','complete')),
 requested_at TEXT NOT NULL)''',
 '''CREATE INDEX IF NOT EXISTS idx_data_requests_owner ON account_data_requests(user_id,requested_at DESC)''',
 '''CREATE TABLE IF NOT EXISTS account_audit_logs (
 id TEXT PRIMARY KEY,actor_id TEXT REFERENCES users(id),actor_type TEXT NOT NULL,
 action TEXT NOT NULL,subject_type TEXT NOT NULL,subject_id TEXT,
 outcome TEXT NOT NULL,reason_code TEXT, occurred_at TEXT NOT NULL)''',
 '''CREATE INDEX IF NOT EXISTS idx_account_audit_time ON account_audit_logs(occurred_at DESC,id DESC)''',
 '''CREATE INDEX IF NOT EXISTS idx_account_audit_actor ON account_audit_logs(actor_id,occurred_at DESC)''',
 '''CREATE TRIGGER IF NOT EXISTS account_audit_no_update BEFORE UPDATE ON account_audit_logs
 BEGIN SELECT RAISE(ABORT,'audit records are append-only'); END''',
 '''CREATE TRIGGER IF NOT EXISTS account_audit_no_delete BEFORE DELETE ON account_audit_logs
 BEGIN SELECT RAISE(ABORT,'audit records are append-only'); END''',
)
CHECKSUM = hashlib.sha256('\n'.join(DDL).encode()).hexdigest()

def migrate(conn:sqlite3.Connection) -> bool:
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute('BEGIN IMMEDIATE')
    try:
        required={'users','sessions','jobs','job_assets','input_assets','user_preferences','auth_events','user_roles','roles','schema_migrations'}
        actual={r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= actual:
            raise RuntimeError('Phase01/02 schema must be verified before Phase05')
        row=conn.execute('SELECT checksum FROM schema_migrations WHERE revision=?',(REVISION,)).fetchone()
        if row:
            if row['checksum']!=CHECKSUM:raise RuntimeError('Phase05 migration checksum mismatch')
            conn.commit();return False
        for statement in DDL:conn.execute(statement)
        conn.execute('INSERT INTO schema_migrations(revision,applied_at,checksum) VALUES(?,?,?)',
                     (REVISION,datetime.now(timezone.utc).isoformat(),CHECKSUM))
        if list(conn.execute('PRAGMA foreign_key_check')):
            raise RuntimeError('Foreign key validation failed')
        conn.commit();return True
    except BaseException:
        conn.rollback();raise
