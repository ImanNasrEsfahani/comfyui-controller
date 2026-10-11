"""Phase 02 cookie/session/CSRF primitives; does not authorize legacy Admin or Worker APIs."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from . import db

COOKIE_NAME = '__Host-comfy_session'
GENERIC_LOGIN = 'Invalid email or password'


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).isoformat()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def configured() -> bool:
    return os.getenv('AUTH_ENABLED', 'false').lower() == 'true'


def policy() -> None:
    if not configured():
        raise HTTPException(503, 'Authentication is not enabled')
    # Fail closed: enabling an unimplemented MFA flag must never weaken security.
    if os.getenv('AUTH_MFA_ENABLED','false').lower() == 'true':
        raise HTTPException(503, 'MFA requires a separately verified implementation')
    secret = os.getenv('AUTH_CSRF_SECRET', '')
    origin = os.getenv('AUTH_PUBLIC_ORIGIN', '')
    parsed = urlsplit(origin)
    if len(secret) < 32 or parsed.scheme != 'https' or not parsed.netloc or parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise HTTPException(503, 'Authentication security configuration is incomplete')


def require_origin(request: Request) -> None:
    policy()
    allowed = os.environ['AUTH_PUBLIC_ORIGIN'].rstrip('/')
    origin = request.headers.get('origin')
    if not origin:
        referer = request.headers.get('referer')
        if referer:
            r = urlsplit(referer)
            origin = f'{r.scheme}://{r.netloc}'
    if not origin or not hmac.compare_digest(origin.rstrip('/'), allowed):
        raise HTTPException(403, 'Untrusted request origin')


def csrf_for_session(raw_session: str) -> str:
    return hmac.new(os.environ['AUTH_CSRF_SECRET'].encode(),
                    ('csrf-v1:' + digest(raw_session)).encode(), hashlib.sha256).hexdigest()


def require_csrf(request: Request) -> None:
    require_origin(request)
    raw = request.cookies.get(COOKIE_NAME, '')
    value = request.headers.get('X-CSRF-Token', '')
    if not raw or len(raw) > 1024 or not value or not hmac.compare_digest(value, csrf_for_session(raw)):
        raise HTTPException(403, 'Invalid CSRF token')


def session_ttls(remember: bool) -> tuple[int,int]:
    # Explicit bounded policies; absolute session limit never exceeds 90 days.
    idle = int(os.getenv('AUTH_IDLE_SECONDS', '3600'))
    absolute = int(os.getenv('AUTH_REMEMBER_SECONDS' if remember else 'AUTH_SESSION_SECONDS',
                             '2592000' if remember else '86400'))
    if not (300 <= idle <= 86400 and 300 <= absolute <= 7776000):
        raise HTTPException(503, 'Invalid authentication timeout configuration')
    return idle, absolute


def create_session(conn, user_id: str, remember: bool) -> tuple[str,str,int]:
    idle, absolute = session_ttls(remember)
    instant = now()
    raw = secrets.token_urlsafe(48)
    sid = secrets.token_hex(16)
    conn.execute('''INSERT INTO sessions(id,user_id,session_token_hash,created_at,last_seen_at,expires_at,
      absolute_expires_at,remember_me) VALUES (?,?,?,?,?,?,?,?)''',
      (sid,user_id,digest(raw),iso(instant),iso(instant),iso(instant+timedelta(seconds=min(idle,absolute))),
       iso(instant+timedelta(seconds=absolute)),int(remember)))
    return sid,raw,absolute


def issue_cookie(response, raw: str, ttl: int):
    response.set_cookie(COOKIE_NAME,raw,max_age=ttl,path='/',secure=True,httponly=True,samesite='lax')
    response.headers['Cache-Control'] = 'no-store'


def clear_cookie(response):
    response.delete_cookie(COOKIE_NAME,path='/',secure=True,httponly=True,samesite='lax')
    response.headers['Cache-Control'] = 'no-store'


def lookup_session(conn, raw: str, *, touch: bool = True):
    if not raw or len(raw) > 1024:
        return None
    entry = conn.execute('''SELECT s.id session_id,s.user_id,s.created_at,s.last_seen_at,s.expires_at,
       s.absolute_expires_at,s.remember_me,u.email,u.email_normalized,u.display_name,u.status,
       u.email_verified_at FROM sessions s JOIN users u ON u.id=s.user_id
       WHERE s.session_token_hash=? AND s.revoked_at IS NULL''',(digest(raw),)).fetchone()
    if entry is None:
        return None
    user = dict(entry)
    instant = now()
    try:
        expiry = datetime.fromisoformat(user['expires_at'])
        absolute = datetime.fromisoformat(user['absolute_expires_at'])
        previous = datetime.fromisoformat(user['last_seen_at'])
    except (ValueError,TypeError):
        return None
    if (instant >= expiry or instant >= absolute or
        user['status'] != 'active' or not user['email_verified_at']):
        return None
    if touch and (instant-previous).total_seconds() >= 60:
        idle,_ = session_ttls(bool(user['remember_me']))
        new_expiry = min(instant+timedelta(seconds=idle),absolute)
        conn.execute('''UPDATE sessions SET last_seen_at=?,expires_at=?
         WHERE id=? AND revoked_at IS NULL''',(iso(instant),iso(new_expiry),user['session_id']))
    user['roles'] = [r['role_id'] for r in conn.execute('SELECT role_id FROM user_roles WHERE user_id=?', (user['user_id'],))]
    return user


def current_user(request: Request):
    policy()
    try:
        with db.connect() as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            entry = lookup_session(conn,request.cookies.get(COOKIE_NAME,''))
    except __import__('sqlite3').OperationalError as exc:
        raise HTTPException(503,'Identity database has not been migrated') from exc
    if not entry:
        raise HTTPException(401,'Authentication required')
    # No session cookie content, password hashes, internal token or provider key in responses.
    return entry


def require_active_user(user=Depends(current_user)):
    if user['status'] != 'active' or not user['email_verified_at']:
        raise HTTPException(403,'Account is not active')
    return user


def require_role(*roles: str):
    def dep(user=Depends(require_active_user)):
        if not set(roles).intersection(user['roles']):
            raise HTTPException(403,'Permission denied')
        return user
    return dep


def safe_user(row: dict) -> dict:
    return {'id':row['user_id'], 'email':row['email'], 'display_name':row['display_name'],
            'status':row['status'],'email_verified':bool(row['email_verified_at']),
            'roles':row.get('roles',[])}
