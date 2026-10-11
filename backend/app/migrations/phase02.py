"""Opt-in additive Phase02 auth support. NEVER run against production automatically."""
from __future__ import annotations
import hashlib
import sqlite3
from datetime import datetime,timezone

REVISION = '004_auth_policy'
DDL = (
    '''CREATE TABLE IF NOT EXISTS auth_invitations (
    id TEXT PRIMARY KEY, email_normalized TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,expires_at TEXT NOT NULL,
    consumed_at TEXT, consumed_by TEXT REFERENCES users(id))''',
    '''CREATE INDEX IF NOT EXISTS idx_auth_invite_email ON auth_invitations(email_normalized,expires_at)''',
    '''CREATE TABLE IF NOT EXISTS auth_rate_limits (
    key_hash TEXT PRIMARY KEY, window_start TEXT NOT NULL,
    hits INTEGER NOT NULL CHECK(hits>=0), blocked_until TEXT)''',
    '''CREATE INDEX IF NOT EXISTS idx_auth_rate_window ON auth_rate_limits(window_start)''',
)
CHECKSUM = hashlib.sha256('\n'.join(DDL).encode()).hexdigest()

def migrate(conn:sqlite3.Connection) -> bool:
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute('BEGIN IMMEDIATE')
    try:
        required={'users','user_roles','sessions','email_verification_tokens','password_reset_tokens','auth_events','schema_migrations'}
        existing={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required.issubset(existing):
            raise RuntimeError('Phase 01 migration must be applied and verified before Phase 02')
        row=conn.execute('SELECT checksum FROM schema_migrations WHERE revision=?',(REVISION,)).fetchone()
        if row:
            if row['checksum'] != CHECKSUM:
                raise RuntimeError('Phase 02 migration checksum mismatch')
            conn.commit()
            return False
        for statement in DDL:
            conn.execute(statement)
        conn.execute('INSERT INTO schema_migrations(revision,applied_at,checksum) VALUES (?,?,?)',
                     (REVISION,datetime.now(timezone.utc).isoformat(),CHECKSUM))
        if list(conn.execute('PRAGMA foreign_key_check')):
            raise RuntimeError('Foreign key integrity check failed')
        conn.commit()
        return True
    except BaseException:
        conn.rollback()
        raise
