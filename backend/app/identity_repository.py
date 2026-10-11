"""Internal Phase 01 owner-scoped data access; NOT a public API/auth middleware.

Callers MUST derive user_id from a validated server-side session in a later
phase. Do not accept user_id from browser JSON, query strings or headers.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError

# Benchmarked/default Argon2id policy must be tuned for the production host.
PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)


class AccessDenied(Exception):
    """Use uniform 'not found' at HTTP boundary for foreign-owned resources."""


class DuplicateRequest(Exception):
    """The same owner's key was re-used with different effective request data."""


def normalized_email(email: str) -> str:
    trimmed = email.strip()
    if (not trimmed or len(trimmed)>254 or trimmed.count('@')!=1
            or trimmed.startswith('@') or trimmed.endswith('@') or any(ch.isspace() for ch in trimmed)):
        raise ValueError('Invalid email')
    # Do not remove dots or plus aliases: that would collapse distinct addresses.
    return trimmed.casefold()


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not (12 <= len(password) <= 1024):
        raise ValueError('Password must be at least 12 characters')
    return PASSWORD_HASHER.hash(password)


def verify_password(stored: str, supplied: str) -> bool:
    try:
        return bool(PASSWORD_HASHER.verify(stored, supplied))
    except (VerifyMismatchError, InvalidHashError, VerificationError, ValueError, TypeError):
        return False


def create_user(conn: sqlite3.Connection, *, email: str, password: str,
                display_name: str, status: str='pending', email_verified_at: str|None=None) -> str:
    if status not in {'pending','active'} or (status=='active' and not email_verified_at):
        raise ValueError('Cannot create an active user without verified email evidence')
    eid = str(uuid4())
    now = utcnow()
    conn.execute('''INSERT INTO users(id,email,email_normalized,password_hash,display_name,status,
       email_verified_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)''',
       (eid,email.strip(),normalized_email(email),hash_password(password),display_name.strip(),status,email_verified_at,now,now))
    conn.execute('INSERT INTO user_roles(user_id,role_id,granted_at) VALUES (?,?,?)',(eid,'user',now))
    return eid


def seed_verified_admin(conn: sqlite3.Connection, *, email: str, password: str,
                         display_name: str, verification_evidence: str, approver: str) -> str:
    """Only invoked by an interactive CLI after an external owner proof.

    Never generate credentials or mark a user active during migration.
    """
    if not verification_evidence.strip() or not approver.strip():
        raise ValueError('Out-of-band owner verification evidence and approver required')
    now = utcnow()
    conn.execute('BEGIN IMMEDIATE')
    try:
        uid = create_user(conn,email=email,password=password,display_name=display_name,
                          status='active',email_verified_at=now)
        conn.execute('INSERT INTO user_roles(user_id,role_id,granted_at) VALUES (?,?,?)',(uid,'admin',now))
        conn.execute('INSERT INTO auth_events(id,user_id,event_type,occurred_at,outcome,safe_details_json) VALUES (?,?,?,?,?,?)',
                     (str(uuid4()),uid,'bootstrap_admin',now,'ok',None))
        # Evidence deliberately stays in local operator record; not job log.
        conn.commit()
        return uid
    except BaseException:
        conn.rollback()
        raise


def user_job(conn: sqlite3.Connection, user_id: str, job_id: str) -> dict[str,Any]|None:
    row = conn.execute('''SELECT * FROM jobs
        WHERE id=? AND owner_user_id=? AND ownership_state='verified' AND hidden=0''',
        (job_id,user_id)).fetchone()
    return dict(row) if row else None


def list_user_jobs(conn: sqlite3.Connection, user_id: str, *, limit:int=30,
                   cursor_at:str|None=None, cursor_id:str|None=None) -> list[dict[str,Any]]:
    if not (1 <= limit <= 100):
        raise ValueError('limit must be between 1 and 100')
    clause='owner_user_id=? AND ownership_state=\'verified\' AND hidden=0'
    args: list[Any]=[user_id]
    if cursor_at is not None or cursor_id is not None:
        if not cursor_at or not cursor_id:
            raise ValueError('A cursor needs both created_at and id')
        clause+=' AND (created_at<? OR (created_at=? AND id<?))'
        args.extend([cursor_at,cursor_at,cursor_id])
    args.append(limit)
    rows=conn.execute('SELECT * FROM jobs WHERE '+clause+' ORDER BY created_at DESC,id DESC LIMIT ?',args).fetchall()
    return [dict(row) for row in rows]


def user_input_asset(conn: sqlite3.Connection, user_id: str, asset_id: str) -> dict[str,Any]|None:
    row=conn.execute('''SELECT * FROM input_assets WHERE asset_id=?
        AND owner_user_id=? AND ownership_state='verified' ''',(asset_id,user_id)).fetchone()
    return dict(row) if row else None


def user_job_asset(conn: sqlite3.Connection, user_id: str, asset_id: str) -> dict[str,Any]|None:
    row=conn.execute('''SELECT a.* FROM job_assets a INNER JOIN jobs j ON a.job_id=j.id
         WHERE a.asset_id=? AND a.owner_user_id=? AND a.ownership_state='verified'
         AND j.owner_user_id=? AND j.ownership_state='verified' AND j.hidden=0''',
         (asset_id,user_id,user_id)).fetchone()
    return dict(row) if row else None


def require_reference(conn: sqlite3.Connection, user_id: str, asset_id: str) -> dict[str,Any]:
    result = user_input_asset(conn,user_id,asset_id) or user_job_asset(conn,user_id,asset_id)
    if result is None:
        raise AccessDenied('Resource not found')
    return result


def user_preset(conn:sqlite3.Connection,user_id:str,preset_id:str) -> dict[str,Any]|None:
    row=conn.execute('SELECT * FROM presets WHERE id=? AND owner_user_id=?',(preset_id,user_id)).fetchone()
    return dict(row) if row else None


def register_idempotency(conn:sqlite3.Connection,*,user_id:str,client_key:str,request_hash:str,job_id:str) -> str:
    """Transaction-safe, owner-specific idempotency mapping. Caller owns transaction.

    Requires already-persisted owner-scoped Job. Does not generate/alter Jobs.
    """
    if not client_key or not request_hash:
        raise ValueError('Non-empty idempotency key and request hash required')
    row=conn.execute('''SELECT request_hash,job_id FROM idempotency_keys
        WHERE owner_user_id=? AND client_key=?''',(user_id,client_key)).fetchone()
    if row:
        if not hmac.compare_digest(row['request_hash'],request_hash):
            raise DuplicateRequest('Idempotency conflict')
        return row['job_id']
    if user_job(conn,user_id,job_id) is None:
        raise AccessDenied('Job must belong to verified owner')
    conn.execute('''INSERT INTO idempotency_keys(owner_user_id,client_key,request_hash,job_id,created_at)
                    VALUES (?,?,?,?,?)''',(user_id,client_key,request_hash,job_id,utcnow()))
    return job_id


def new_session_token() -> str:
    """Opaque server-side bearer material: never store plaintext in database."""
    return secrets.token_urlsafe(48)


def digest_session_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def legacy_controller_owner(conn: sqlite3.Connection) -> str|None:
    """Return only the explicitly approved original Controller operator account.

    No table or no approval means legacy ownerless behavior (compatibility).
    Refuse ambiguous approvals rather than picking an arbitrary last user.
    """
    exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_owner_approvals'").fetchone()
    if not exists:
        return None
    rows=conn.execute('SELECT DISTINCT user_id FROM legacy_owner_approvals').fetchall()
    if len(rows)>1:
        raise RuntimeError('Conflicting legacy owner approvals')
    return rows[0][0] if rows else None


def issue_session(conn: sqlite3.Connection, *, user_id: str, ttl_seconds: int,
                  absolute_ttl_seconds: int, remember_me: bool=False) -> tuple[str,str]:
    """Create DB-hashed session. Caller decides TTL per approved ADR.

    The returned token must be sent only in a Secure/HttpOnly cookie by a
    future auth middleware. This module never sends/stores the plaintext.
    """
    from datetime import timedelta
    if not (60 <= ttl_seconds <= absolute_ttl_seconds <= 60*60*24*90):
        raise ValueError('Session TTL policy must be explicitly provided and bounded')
    user=conn.execute('''SELECT status,email_verified_at FROM users WHERE id=?''',(user_id,)).fetchone()
    if not user or user['status']!='active' or not user['email_verified_at']:
        raise AccessDenied('Inactive or unverified account')
    now=datetime.now(timezone.utc)
    token=new_session_token()
    session_id=str(uuid4())
    conn.execute('''INSERT INTO sessions(id,user_id,session_token_hash,created_at,last_seen_at,
        expires_at,absolute_expires_at,remember_me) VALUES (?,?,?,?,?,?,?,?)''',
        (session_id,user_id,digest_session_token(token),now.isoformat(),now.isoformat(),
         (now+timedelta(seconds=ttl_seconds)).isoformat(),
         (now+timedelta(seconds=absolute_ttl_seconds)).isoformat(),int(remember_me)))
    return session_id,token


def current_session_user(conn:sqlite3.Connection, token: str) -> dict[str,Any]|None:
    """Read-only proof that a session is active. Future HTTP layer adds CSRF.

    No sliding expiry or audit side effects; token compared via SHA256 digest.
    """
    if not token or len(token)>1024:
        return None
    now=utcnow()
    row=conn.execute('''SELECT u.id,u.status,u.email_verified_at,u.token_version
        FROM sessions s JOIN users u ON s.user_id=u.id
        WHERE s.session_token_hash=? AND s.revoked_at IS NULL
          AND s.expires_at>? AND s.absolute_expires_at>?
          AND u.status='active' AND u.email_verified_at IS NOT NULL''',
        (digest_session_token(token),now,now)).fetchone()
    return dict(row) if row else None


def revoke_session(conn:sqlite3.Connection, user_id:str, session_id:str) -> bool:
    cur=conn.execute('''UPDATE sessions SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL''',
                     (utcnow(),session_id,user_id))
    return cur.rowcount>0


def revoke_all_sessions(conn:sqlite3.Connection, user_id:str) -> int:
    cur=conn.execute('''UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL''',
                     (utcnow(),user_id))
    conn.execute('UPDATE users SET token_version=token_version+1,updated_at=? WHERE id=?',(utcnow(),user_id))
    return cur.rowcount
