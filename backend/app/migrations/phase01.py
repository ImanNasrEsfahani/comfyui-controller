"""Phase 01 identity/ownership migration for the existing SQLite database.

No network calls and no real-user backfill. Invoke explicitly on a private COPY;
never import this module from the application startup event.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REVISIONS = ("001_identity", "002_owner_columns", "003_legacy_review")
TABLES = ("jobs", "workflows", "input_assets", "job_assets")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def objects(conn: sqlite3.Connection, kind: str = 'table') -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type=?", (kind,))}


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if table not in objects(conn):
        return set()
    return {r[1] for r in conn.execute('PRAGMA table_info("' + table + '")')}


def begin(conn: sqlite3.Connection) -> None:
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute('BEGIN IMMEDIATE')


def migrate(conn: sqlite3.Connection) -> dict[str, Any]:
    """Additive migrations. Concurrent invocation serialized by BEGIN IMMEDIATE.

    FK target checks occur on INSERT/UPDATE. No record counts, IDs, or secrets
    leave this function; caller may report counts independently.
    """
    conn.row_factory = sqlite3.Row
    begin(conn)
    try:
        legacy = objects(conn)
        if not {'jobs', 'input_assets', 'job_assets', 'workflows'} <= legacy:
            raise RuntimeError('Expected initialized Controller SQLite schema; run legacy init_db only on a disposable copy first')
        conn.execute('''CREATE TABLE IF NOT EXISTS schema_migrations (
            revision TEXT PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)''')
        applied = {r['revision']: r['checksum'] for r in conn.execute('SELECT * FROM schema_migrations')}
        steps = (_identity_tables, _owner_columns, _review_legacy)
        for revision, fn in zip(REVISIONS, steps):
            checksum = hashlib.sha256(fn.__code__.co_code + str(fn.__code__.co_consts).encode()).hexdigest()
            if revision in applied:
                if applied[revision] != checksum:
                    raise RuntimeError(f'Migration code changed after revision {revision} was applied')
                continue
            fn(conn)
            conn.execute('INSERT INTO schema_migrations VALUES (?,?,?)', (revision, utcnow(), checksum))
        fk_errors = list(conn.execute('PRAGMA foreign_key_check'))
        if fk_errors:
            raise RuntimeError(f'foreign_key_check found {len(fk_errors)} violations')
        result = {'revision': REVISIONS[-1], 'applied': [r['revision'] for r in conn.execute('SELECT revision FROM schema_migrations ORDER BY revision')],
                  'unclaimed_jobs': conn.execute('SELECT COUNT(*) FROM jobs WHERE owner_user_id IS NULL').fetchone()[0],
                  'unclaimed_input_assets': conn.execute('SELECT COUNT(*) FROM input_assets WHERE owner_user_id IS NULL').fetchone()[0],
                  'unclaimed_job_assets': conn.execute('SELECT COUNT(*) FROM job_assets WHERE owner_user_id IS NULL').fetchone()[0]}
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise


def _identity_tables(conn: sqlite3.Connection) -> None:
    ddl = (
        '''CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL, email_normalized TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, display_name TEXT NOT NULL, status TEXT NOT NULL
        CHECK(status IN ('pending','active','suspended','deletion_requested','deleted')),
        email_verified_at TEXT, avatar_asset_id TEXT, locale TEXT, timezone TEXT,
        token_version INTEGER NOT NULL DEFAULT 0, last_login_at TEXT, deleted_at TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
        '''CREATE TABLE roles (id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '')''',
        '''CREATE TABLE permissions (id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE)''',
        '''CREATE TABLE role_permissions (role_id TEXT NOT NULL REFERENCES roles(id),
        permission_id TEXT NOT NULL REFERENCES permissions(id), PRIMARY KEY(role_id,permission_id))''',
        '''CREATE TABLE user_roles (user_id TEXT NOT NULL REFERENCES users(id),
        role_id TEXT NOT NULL REFERENCES roles(id), granted_by TEXT REFERENCES users(id),
        granted_at TEXT NOT NULL, PRIMARY KEY(user_id,role_id))''',
        '''CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
        session_token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL, expires_at TEXT NOT NULL, absolute_expires_at TEXT NOT NULL,
        revoked_at TEXT, remember_me INTEGER NOT NULL DEFAULT 0, mfa_level INTEGER NOT NULL DEFAULT 0,
        ip_hash TEXT, user_agent_summary TEXT)''',
        '''CREATE TABLE email_verification_tokens (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
        token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, consumed_at TEXT,
        created_at TEXT NOT NULL, resend_count INTEGER NOT NULL DEFAULT 0)''',
        '''CREATE TABLE password_reset_tokens (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
        token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, consumed_at TEXT,
        requested_at TEXT NOT NULL, source_ip_hash TEXT)''',
        '''CREATE TABLE mfa_methods (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
        method_type TEXT NOT NULL, encrypted_secret_ref TEXT NOT NULL,
        verified_at TEXT, created_at TEXT NOT NULL, revoked_at TEXT)''',
        '''CREATE TABLE mfa_recovery_codes (id TEXT PRIMARY KEY, mfa_method_id TEXT NOT NULL REFERENCES mfa_methods(id),
        code_hash TEXT NOT NULL, consumed_at TEXT, issued_at TEXT NOT NULL)''',
        '''CREATE TABLE auth_events (id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id),
        event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, outcome TEXT NOT NULL,
        ip_hash TEXT, safe_details_json TEXT)''',
        '''CREATE TABLE user_preferences (user_id TEXT PRIMARY KEY REFERENCES users(id),
        theme TEXT, locale TEXT, timezone TEXT, default_model_id TEXT,
        default_ratio TEXT, alerts_json TEXT, updated_at TEXT NOT NULL)''',
        '''CREATE TABLE presets (id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL REFERENCES users(id),
        workflow_id TEXT REFERENCES workflows(id), workflow_version TEXT, model_version_id TEXT,
        name TEXT NOT NULL, fields_json TEXT NOT NULL,
        includes_prompts INTEGER NOT NULL DEFAULT 0, seed_policy TEXT,
        is_default INTEGER NOT NULL DEFAULT 0, schema_version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(owner_user_id,workflow_id,name))''',
        '''CREATE TABLE idempotency_keys (owner_user_id TEXT NOT NULL REFERENCES users(id),
        client_key TEXT NOT NULL, request_hash TEXT NOT NULL,
        job_id TEXT NOT NULL REFERENCES jobs(id), created_at TEXT NOT NULL, expires_at TEXT,
        PRIMARY KEY(owner_user_id,client_key))''',
        '''CREATE TABLE legacy_owner_approvals (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
        approved_by TEXT NOT NULL, approved_at TEXT NOT NULL, source_sha TEXT NOT NULL,
        evidence_ref TEXT NOT NULL, notes TEXT)''',
        '''CREATE TABLE owner_review_queue (resource_type TEXT NOT NULL,
        resource_id TEXT NOT NULL, reason_code TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'quarantined'
        CHECK(status IN ('quarantined','verified','rejected')),
        recorded_at TEXT NOT NULL, resolved_at TEXT, resolved_by TEXT REFERENCES users(id),
        PRIMARY KEY(resource_type,resource_id))''',
    )
    for statement in ddl:
        conn.execute(statement.replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ', 1))
    for role in ('user','admin','operator','support','superadmin'):
        conn.execute('INSERT OR IGNORE INTO roles(id,code) VALUES (?,?)', (role,role))
    for name in ('users','sessions','user_roles','auth_events'):
        # Only additive supporting indexes, no index on secrets or private strings.
        pass
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sessions_user_exp ON sessions(user_id,expires_at)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_auth_events_user_time ON auth_events(user_id,occurred_at)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_presets_owner_created ON presets(owner_user_id,created_at,id)')


def _owner_columns(conn: sqlite3.Connection) -> None:
    for table in ('jobs','input_assets','job_assets'):
        if 'owner_user_id' not in columns(conn, table):
            conn.execute(f'ALTER TABLE {table} ADD COLUMN owner_user_id TEXT REFERENCES users(id)')
        if 'ownership_state' not in columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN ownership_state TEXT NOT NULL DEFAULT 'unclaimed'")
        if 'ownership_state' in columns(conn, table):
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS trg_{table}_ownership_guard
            BEFORE INSERT ON {table} WHEN NEW.ownership_state='verified' AND NEW.owner_user_id IS NULL
            BEGIN SELECT RAISE(ABORT,'verified ownership requires owner'); END''')
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS trg_{table}_ownership_guard_update
            BEFORE UPDATE OF ownership_state,owner_user_id ON {table}
            WHEN NEW.ownership_state='verified' AND NEW.owner_user_id IS NULL
            BEGIN SELECT RAISE(ABORT,'verified ownership requires owner'); END''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_jobs_owner_time ON jobs(owner_user_id,created_at DESC,id DESC)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_jobs_owner_state_time ON jobs(owner_user_id,state,created_at DESC,id DESC)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_input_assets_owner_time ON input_assets(owner_user_id,created_at DESC,asset_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_job_assets_owner_time ON job_assets(owner_user_id,created_at DESC,asset_id)')
    conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_owner_request
    ON jobs(owner_user_id,client_request_id)
    WHERE owner_user_id IS NOT NULL AND client_request_id IS NOT NULL''')
    # KEEP the old global unique index until the current legacy app helpers
    # are updated. Dropping it here would risk user/legacy idempotency races.


def _review_legacy(conn: sqlite3.Connection) -> None:
    # No automatic ownership inference. Existing rows stay private and unclaimed.
    now = utcnow()
    for table, pk in (('jobs','id'),('input_assets','asset_id'),('job_assets','asset_id')):
        conn.execute(f'''INSERT OR IGNORE INTO owner_review_queue
        (resource_type,resource_id,reason_code,recorded_at)
        SELECT ?,{pk},'no_verified_owner',? FROM {table}
        WHERE owner_user_id IS NULL''', (table,now))


def approve_legacy_owner(conn: sqlite3.Connection, user_id: str, approval_ref: str,
                         approved_by: str, source_sha: str, *, apply: bool=False) -> dict:
    """Controlled review, NEVER called by migrate(). All approvals external.

    Only unclaimed jobs/assets enter backfill. Detached/orphan assets remain
    quarantined, not attributed to a random user. Must run on a copy first.
    """
    if not approval_ref or not approved_by or not source_sha:
        raise ValueError('Explicit evidence reference, approver and source SHA required')
    if not apply:
        return {'dry_run': True, 'note': 'Approval supplied; no rows changed'}
    begin(conn)
    try:
        user = conn.execute("SELECT id,status FROM users WHERE id=?", (user_id,)).fetchone()
        if not user or user[1] != 'active':
            raise ValueError('Owner must be an existing active, verified account')
        verified = conn.execute('SELECT email_verified_at FROM users WHERE id=?',(user_id,)).fetchone()[0]
        if not verified:
            raise ValueError('Verified email required before historical attribution')
        now=utcnow()
        old_approvers=conn.execute('SELECT DISTINCT user_id FROM legacy_owner_approvals').fetchall()
        if any(row[0] != user_id for row in old_approvers):
            raise ValueError('Conflicting previously-approved owner; manual reconciliation required')
        conn.execute('''INSERT INTO legacy_owner_approvals VALUES (?,?,?,?,?,?,NULL)''',
                     (hashlib.sha256((user_id+approval_ref).encode()).hexdigest()[:32],user_id,approved_by,now,source_sha,approval_ref))
        # Jobs from this controller's legacy single operator may be claimed only
        # with explicit approval. Orphan inputs/outputs are NOT claimed.
        conn.execute("UPDATE jobs SET owner_user_id=?,ownership_state='verified' WHERE owner_user_id IS NULL",(user_id,))
        conn.execute('''UPDATE job_assets SET owner_user_id=?,ownership_state='verified'
          WHERE owner_user_id IS NULL AND EXISTS
          (SELECT 1 FROM jobs WHERE jobs.id=job_assets.job_id AND jobs.owner_user_id=?)''',(user_id,user_id))
        # Legacy standalone inputs do not currently have an FK to Job; require
        # separate forensic mapping before attribution; leave quarantined.
        conn.execute('''UPDATE owner_review_queue SET status='verified',resolved_at=?,resolved_by=?
          WHERE (resource_type='jobs' OR resource_type='job_assets') AND EXISTS (
             SELECT 1 FROM jobs WHERE jobs.id=owner_review_queue.resource_id AND owner_review_queue.resource_type='jobs'
             UNION ALL SELECT 1 FROM job_assets WHERE job_assets.asset_id=owner_review_queue.resource_id AND owner_review_queue.resource_type='job_assets')''',(now,user_id))
        result={'job_count':conn.execute('SELECT COUNT(*) FROM jobs WHERE owner_user_id=?',(user_id,)).fetchone()[0],
                'job_asset_count':conn.execute('SELECT COUNT(*) FROM job_assets WHERE owner_user_id=?',(user_id,)).fetchone()[0],
                'inputs_still_unclaimed':conn.execute('SELECT COUNT(*) FROM input_assets WHERE owner_user_id IS NULL').fetchone()[0]}
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise


def backup_copy(source: Path, destination: Path) -> None:
    """SQLite online backup API, never shutil.copyfile on WAL-enabled DB."""
    if source.resolve() == destination.resolve():
        raise ValueError('Refuse to overwrite the source SQLite database')
    if not source.is_file() or destination.exists():
        raise ValueError('Source must exist; destination must not exist')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
            integrity = dst.execute('PRAGMA integrity_check').fetchone()[0]
            if integrity != 'ok':
                raise RuntimeError('Backup integrity check failed')


def activate_scoped_idempotency(conn: sqlite3.Connection, *, patched_source: Path, patched_db_source: Path) -> dict[str,int]:
    """COPY ONLY: enable per-owner job uniqueness after helper source is patched.

    Caller must coordinate server maintenance; no activation during migration up.
    """
    code=patched_source.read_text('utf-8')
    if ('idx_jobs_legacy_request' not in code or
        'legacy_controller_owner' not in code or
        'idx_jobs_owner_request' not in code):
        raise RuntimeError('Legacy job_records.py helper patch not installed; refusing to drop global uniqueness')
    db_code=patched_db_source.read_text('utf-8')
    if 'controller_owner_id' not in db_code or 'legacy_controller_owner' not in db_code:
        raise RuntimeError('Legacy db.py create_job patch not installed; refusing global index removal')
    begin(conn)
    try:
        if 'owner_user_id' not in columns(conn,'jobs'):
            raise RuntimeError('Apply Phase01 ownership schema first')
        duplicates=conn.execute('''SELECT owner_user_id,client_request_id,COUNT(*) n FROM jobs
            WHERE owner_user_id IS NOT NULL AND client_request_id IS NOT NULL
            GROUP BY owner_user_id,client_request_id HAVING COUNT(*)>1 LIMIT 1''').fetchone()
        if duplicates:
            raise RuntimeError('Owner-scoped duplicate jobs require manual resolution')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_legacy_request ON jobs(client_request_id) WHERE owner_user_id IS NULL AND client_request_id IS NOT NULL')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_owner_request ON jobs(owner_user_id,client_request_id) WHERE owner_user_id IS NOT NULL AND client_request_id IS NOT NULL')
        conn.execute('DROP INDEX IF EXISTS idx_jobs_client_request')
        revision_checksum=hashlib.sha256(patched_source.read_bytes()+patched_db_source.read_bytes()).hexdigest()
        conn.execute("INSERT OR IGNORE INTO schema_migrations(revision,applied_at,checksum) VALUES ('004_scoped_keys',?,?)",(utcnow(),revision_checksum))
        remaining=conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='idx_jobs_client_request'").fetchone()[0]
        if remaining:
            raise RuntimeError('Global legacy request index was not removed')
        conn.commit()
        return {'global_index_remaining':remaining}
    except BaseException:
        conn.rollback()
        raise


def downgrade_empty_copy(conn: sqlite3.Connection) -> dict:
    """Undo this additive schema ONLY on a disposable copy with no identity data.

    Old Job/Asset rows remain untouched. Unsafe reversals (claimed ownership,
    real users or new idempotency data) are rejected; use SQLite backup restore.
    """
    begin(conn)
    try:
        if not {'users','schema_migrations'} <= objects(conn):
            raise RuntimeError('Phase01 revision was not installed')
        identities=conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        owned=sum(conn.execute(f'SELECT COUNT(*) FROM {t} WHERE owner_user_id IS NOT NULL').fetchone()[0]
                  for t in ('jobs','input_assets','job_assets'))
        if identities or owned:
            raise RuntimeError('Irreversible identity/ownership activity; restore validated backup instead')
        for t in ('jobs','input_assets','job_assets'):
            for suffix in ('ownership_guard','ownership_guard_update'):
                conn.execute(f'DROP TRIGGER IF EXISTS trg_{t}_{suffix}')
        for name in ('idx_jobs_owner_request','idx_jobs_legacy_request','idx_jobs_owner_time',
                     'idx_jobs_owner_state_time','idx_input_assets_owner_time','idx_job_assets_owner_time'):
            conn.execute(f'DROP INDEX IF EXISTS {name}')
        for t in ('jobs','input_assets','job_assets'):
            for col in ('ownership_state','owner_user_id'):
                if col in columns(conn,t):
                    conn.execute(f'ALTER TABLE {t} DROP COLUMN {col}')
        # If index was activated, return old baseline uniqueness.
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_client_request
            ON jobs(client_request_id) WHERE client_request_id IS NOT NULL''')
        for table in ('idempotency_keys','owner_review_queue','legacy_owner_approvals',
             'mfa_recovery_codes','mfa_methods','auth_events','email_verification_tokens',
             'password_reset_tokens','sessions','user_preferences','presets','user_roles',
             'role_permissions','permissions','roles','users','schema_migrations'):
            conn.execute('DROP TABLE IF EXISTS '+table)
        conn.commit()
        return {'downgraded':True,'legacy_tables_preserved':True}
    except BaseException:
        conn.rollback()
        raise
