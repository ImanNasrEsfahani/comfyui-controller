"""Phase02: isolated user authentication APIs; legacy admin/worker APIs stay unchanged.

The router is disabled by default. Only explicit offline migrations prepare schema.
Public account pages belong to Phase04; a successful User session is NOT GPU authorization.
"""
from __future__ import annotations
from contextlib import contextmanager
import hmac
import hashlib
import os
import secrets
import sqlite3
from datetime import timedelta
from uuid import uuid4
from typing import Annotated

from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from . import db, identity_repository as identity, security
from .auth_mail import email_sender, SMTPMailer


@contextmanager
def auth_db():
    with db.connect() as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn


def require_ready():
    security.policy()
    with auth_db() as conn:
        required={'users','sessions','auth_rate_limits','auth_invitations','email_verification_tokens','password_reset_tokens'}
        existing={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required.issubset(existing):
            raise HTTPException(503,'Identity migration not applied')

router=APIRouter(prefix='/api/auth',tags=['Authentication'],dependencies=[Depends(require_ready)])

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')

class Register(Strict):
    email: str = Field(min_length=3,max_length=254)
    password: str = Field(min_length=12,max_length=1024)
    display_name: str = Field(min_length=1,max_length=150)
    invite_token: str | None = Field(default=None,max_length=200)
    terms_accepted: bool

class Credentials(Strict):
    email: str
    password: str
    remember_me: bool = False

class Token(Strict):
    token: str = Field(min_length=32,max_length=512)

class Email(Strict):
    email: str

class Reset(Token):
    new_password: str = Field(min_length=12,max_length=1024)

class Change(Strict):
    current_password: str
    new_password: str = Field(min_length=12,max_length=1024)

GENERIC_SENT={'message':'If the account is eligible, an email will be sent.'}


def normalized(email: str) -> str:
    try:
        return identity.normalized_email(email)
    except ValueError as exc:
        raise HTTPException(422,'Invalid email address') from exc


def password_hash(password: str) -> str:
    # deny widely used values and obvious placeholder credentials in addition to Argon2id.
    lowered=password.strip().casefold()
    if (len(password)<12 or len(password)>1024 or lowered in {
        'password123456','123456789012','qwerty123456','admin12345678',
        'passwordpassword','letmein123456','correcthorsebatterystaple'}):
        raise HTTPException(422,'Choose a stronger password of at least 12 characters')
    try:
        return identity.hash_password(password)
    except ValueError as exc:
        raise HTTPException(422,'Invalid password') from exc


def log_event(conn,user_id,event,outcome):
    conn.execute('''INSERT INTO auth_events(id,user_id,event_type,occurred_at,outcome) VALUES (?,?,?,?,?)''',
                 (str(uuid4()),user_id,event,security.iso(),outcome))


def hashed_bucket(action: str, value: str) -> str:
    return hmac.new(os.environ['AUTH_CSRF_SECRET'].encode(),
                    f'{action}|{value}'.encode(),hashlib.sha256).hexdigest()


def limit(conn, action: str, value: str, max_hits: int, window_seconds: int = 900) -> None:
    """Transactional, privacy-minimal fixed window. Called inside BEGIN IMMEDIATE."""
    key=hashed_bucket(action,value)
    now=security.now()
    row=conn.execute('SELECT hits,window_start,blocked_until FROM auth_rate_limits WHERE key_hash=?',(key,)).fetchone()
    if row:
        from datetime import datetime
        if row['blocked_until'] and datetime.fromisoformat(row['blocked_until'])>now:
            raise HTTPException(429,'Too many requests; try again later')
        if (now-datetime.fromisoformat(row['window_start'])).total_seconds()<window_seconds:
            if row['hits']>=max_hits:
                conn.execute('UPDATE auth_rate_limits SET blocked_until=? WHERE key_hash=?',
                             (security.iso(now+timedelta(seconds=window_seconds)),key))
                # Persist lock even when throwing. Commit before raising.
                conn.commit()
                raise HTTPException(429,'Too many requests; try again later')
            conn.execute('UPDATE auth_rate_limits SET hits=hits+1 WHERE key_hash=?',(key,))
            return
    conn.execute('''INSERT INTO auth_rate_limits(key_hash,window_start,hits,blocked_until)
                   VALUES (?,?,1,NULL) ON CONFLICT(key_hash) DO UPDATE SET
                   window_start=excluded.window_start,hits=1,blocked_until=NULL''',(key,security.iso(now)))


def reset_bucket(conn, action, value):
    conn.execute('DELETE FROM auth_rate_limits WHERE key_hash=?',(hashed_bucket(action,value),))


def create_one_time(conn, table: str,user_id: str, ttl: int) -> str:
    if table not in ('email_verification_tokens','password_reset_tokens'):
        raise ValueError('Unexpected token table')
    raw=secrets.token_urlsafe(40)
    now=security.now()
    time_col='created_at' if table=='email_verification_tokens' else 'requested_at'
    conn.execute(f'''INSERT INTO {table}(id,user_id,token_hash,expires_at,{time_col})
                     VALUES (?,?,?,?,?)''',(str(uuid4()),user_id,security.digest(raw),
                     security.iso(now+timedelta(seconds=ttl)),security.iso(now)))
    return raw


def send_token(sender, recipient: str, category: str, token: str):
    origin=os.environ['AUTH_PUBLIC_ORIGIN'].rstrip('/')
    if category=='verify':
        url=f'{origin}/verify-email#token={token}'
        subject='Verify your email'
        message=f'Open this link to verify your account. It expires in 30 minutes:\n{url}'
    else:
        url=f'{origin}/reset-password#token={token}'
        subject='Reset your password'
        message=f'Open this link to reset your password. It expires in 30 minutes:\n{url}'
    # URL fragment keeps the secret out of HTTP access logs and Referer requests.
    sender.send(recipient,subject,message)


def safe_mail_delivery(sender, recipient: str, category: str, token: str):
    """Background delivery; do not expose address/token/provider failure to HTTP client or logs."""
    try:
        send_token(sender,recipient,category,token)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Auth email delivery failed; check private SMTP configuration')


def ensure_mail_config(sender):
    if isinstance(sender, SMTPMailer) and not (os.getenv('AUTH_SMTP_HOST') and os.getenv('AUTH_SMTP_FROM')):
        raise HTTPException(503,'Transactional email service not configured')


def current(request:Request):
    return security.current_user(request)


def auth_mutation(request:Request):
    security.require_origin(request)


def cookie_mutation(request:Request):
    security.require_csrf(request)
    return security.current_user(request)


@router.post('/register',status_code=202,dependencies=[Depends(auth_mutation)])
def register(body:Register,background:BackgroundTasks,request:Request,mail=Depends(email_sender)):
    mode=os.getenv('AUTH_REGISTRATION_MODE','invite').strip().lower()
    if mode not in {'invite','public','disabled'}:
        raise HTTPException(503,'Invalid registration policy')
    if mode=='disabled':
        raise HTTPException(403,'Registration is disabled')
    if not body.terms_accepted:
        raise HTTPException(422,'Accept the terms to continue')
    ensure_mail_config(mail)
    email=normalized(body.email)
    # Throttle before the intentionally CPU-expensive Argon2 calculation.
    with auth_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        limit(conn,'register-ip',request.client.host if request.client else 'unknown',20,3600)
    valid_hash=password_hash(body.password)
    token=None
    with auth_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        limit(conn,'register',email,4,3600)
        if mode=='invite':
            if not body.invite_token:
                raise HTTPException(403,'Valid invitation required')
            invite=conn.execute('''SELECT id FROM auth_invitations WHERE email_normalized=? AND token_hash=?
               AND consumed_at IS NULL AND expires_at>?''',
               (email,security.digest(body.invite_token),security.iso())).fetchone()
            if invite is None:
                raise HTTPException(403,'Valid invitation required')
        existing=conn.execute('SELECT id FROM users WHERE email_normalized=?',(email,)).fetchone()
        if existing:
            return GENERIC_SENT
        uid=str(uuid4())
        instant=security.iso()
        conn.execute('''INSERT INTO users(id,email,email_normalized,password_hash,display_name,status,
          created_at,updated_at) VALUES (?,?,?,?,?,'pending',?,?)''',
          (uid,body.email.strip(),email,valid_hash,body.display_name.strip(),instant,instant))
        conn.execute('INSERT INTO user_roles(user_id,role_id,granted_at) VALUES (?,?,?)',(uid,'user',instant))
        if mode=='invite':
            conn.execute('''UPDATE auth_invitations SET consumed_at=?,consumed_by=? WHERE id=? AND consumed_at IS NULL''',
                         (instant,uid,invite['id']))
        token=create_one_time(conn,'email_verification_tokens',uid,1800)
        log_event(conn,uid,'register','pending')
    background.add_task(safe_mail_delivery,mail,body.email.strip(),'verify',token)
    return GENERIC_SENT


@router.post('/verify-email',dependencies=[Depends(auth_mutation)])
def verify_email(body:Token):
    with auth_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        record=conn.execute('''SELECT t.id,t.user_id,u.status FROM email_verification_tokens t
           JOIN users u ON u.id=t.user_id WHERE t.token_hash=? AND t.consumed_at IS NULL AND t.expires_at>?''',
           (security.digest(body.token),security.iso())).fetchone()
        if record is None or record['status']!='pending':
            raise HTTPException(409,'Verification link is invalid or expired')
        moment=security.iso()
        conn.execute('UPDATE email_verification_tokens SET consumed_at=? WHERE id=?',(moment,record['id']))
        conn.execute('''UPDATE users SET status='active',email_verified_at=?,updated_at=? WHERE id=? AND status='pending' ''',
                     (moment,moment,record['user_id']))
        log_event(conn,record['user_id'],'verify_email','ok')
    return {'message':'Email verified; you can now sign in.'}


@router.post('/resend-verification',status_code=202,dependencies=[Depends(auth_mutation)])
def resend(body:Email,background:BackgroundTasks,mail=Depends(email_sender)):
    email=normalized(body.email)
    raw=None
    with auth_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        limit(conn,'resend',email,3,3600)
        row=conn.execute("SELECT id,email FROM users WHERE email_normalized=? AND status='pending'",(email,)).fetchone()
        if row:
            recent=conn.execute('''SELECT created_at FROM email_verification_tokens
              WHERE user_id=? ORDER BY created_at DESC LIMIT 1''',(row['id'],)).fetchone()
            if recent:
                from datetime import datetime
                if (security.now()-datetime.fromisoformat(recent['created_at'])).total_seconds()<60:
                    return GENERIC_SENT
            raw=create_one_time(conn,'email_verification_tokens',row['id'],1800)
    if raw:
        background.add_task(safe_mail_delivery,mail,row['email'],'verify',raw)
    return GENERIC_SENT


@router.post('/login',dependencies=[Depends(auth_mutation)])
def login(body:Credentials,response:Response,request:Request):
    email=normalized(body.email)
    with auth_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        limit(conn,'login-ip',request.client.host if request.client else 'unknown',100,3600)
        limit(conn,'login',email,5,900)
        row=conn.execute('''SELECT id,password_hash,status,email_verified_at FROM users
                            WHERE email_normalized=?''',(email,)).fetchone()
        # Deliberately generic response for unknown, suspended and unverified accounts.
        if not row or not identity.verify_password(row['password_hash'],body.password) or row['status']!='active' or not row['email_verified_at']:
            conn.commit()  # Retain the failed-login rate counter despite HTTP 401.
            raise HTTPException(401, 'Invalid email or password')
        if identity.PASSWORD_HASHER.check_needs_rehash(row['password_hash']):
            conn.execute('UPDATE users SET password_hash=?,updated_at=? WHERE id=?',
                         (password_hash(body.password),security.iso(),row['id']))
        session_id,raw,ttl=security.create_session(conn,row['id'],body.remember_me)
        conn.execute('UPDATE users SET last_login_at=? WHERE id=?',(security.iso(),row['id']))
        reset_bucket(conn,'login',email)
        log_event(conn,row['id'],'login','ok')
    security.issue_cookie(response,raw,ttl)
    return {'authenticated':True,'state':'authenticated'}


@router.get('/me')
def me(user=Depends(current)):
    return {'state':'authenticated','user':security.safe_user(user)}

@router.get('/session')
def session(request:Request):
    try:
        user=security.current_user(request)
    except HTTPException as exc:
        if exc.status_code==401:
            return {'state':'anonymous','user':None}
        raise
    return {'state':'authenticated','user':security.safe_user(user)}

@router.get('/csrf')
def csrf(request:Request,user=Depends(current)):
    raw=request.cookies.get(security.COOKIE_NAME,'')
    return {'csrf_token':security.csrf_for_session(raw)}

@router.post('/logout')
def logout(request:Request,response:Response,user=Depends(cookie_mutation)):
    with auth_db() as conn:
        conn.execute('UPDATE sessions SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL',
                     (security.iso(),user['session_id'],user['user_id']))
        log_event(conn,user['user_id'],'logout','ok')
    security.clear_cookie(response)
    return {'authenticated':False}

@router.post('/logout-all')
def logout_all(response:Response,user=Depends(cookie_mutation)):
    with auth_db() as conn:
        conn.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',
                     (security.iso(),user['user_id']))
        log_event(conn,user['user_id'],'logout_all','ok')
    security.clear_cookie(response)
    return {'authenticated':False}

@router.get('/sessions')
def sessions(user=Depends(current)):
    with auth_db() as conn:
        rows=conn.execute('''SELECT id,created_at,last_seen_at,expires_at,remember_me FROM sessions
          WHERE user_id=? AND revoked_at IS NULL AND expires_at>? AND absolute_expires_at>?
          ORDER BY created_at DESC LIMIT 100''',(user['user_id'],security.iso(),security.iso())).fetchall()
        return {'sessions':[{'id':r['id'],'created_at':r['created_at'],'last_seen_at':r['last_seen_at'],
           'expires_at':r['expires_at'],'remember_me':bool(r['remember_me']),
           'current':r['id']==user['session_id']} for r in rows]}

@router.delete('/sessions/{session_id}',status_code=204)
def revoke_session(session_id:str,user=Depends(cookie_mutation)):
    with auth_db() as conn:
        cur=conn.execute('''UPDATE sessions SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL''',
                        (security.iso(),session_id,user['user_id']))
        if not cur.rowcount:
            raise HTTPException(404,'Session not found')
    return Response(status_code=204)

@router.post('/forgot-password',status_code=202,dependencies=[Depends(auth_mutation)])
def forgot(body:Email,background:BackgroundTasks,mail=Depends(email_sender)):
    email=normalized(body.email)
    raw=None
    with auth_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        limit(conn,'forgot',email,3,3600)
        row=conn.execute('''SELECT id,email FROM users WHERE email_normalized=?
                            AND status='active' AND email_verified_at IS NOT NULL''',(email,)).fetchone()
        if row:
            raw=create_one_time(conn,'password_reset_tokens',row['id'],1800)
    if raw:
        background.add_task(safe_mail_delivery,mail,row['email'],'reset',raw)
    return GENERIC_SENT

@router.post('/reset-password',dependencies=[Depends(auth_mutation)])
def reset(body:Reset,response:Response):
    encoded=password_hash(body.new_password)
    with auth_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('''SELECT t.id,t.user_id FROM password_reset_tokens t JOIN users u ON u.id=t.user_id
          WHERE t.token_hash=? AND t.consumed_at IS NULL AND t.expires_at>?
           AND u.status='active' AND u.email_verified_at IS NOT NULL''',
           (security.digest(body.token),security.iso())).fetchone()
        if not row:
            raise HTTPException(409,'Reset link is invalid or expired')
        moment=security.iso()
        conn.execute('UPDATE password_reset_tokens SET consumed_at=? WHERE id=?',(moment,row['id']))
        conn.execute('UPDATE users SET password_hash=?,token_version=token_version+1,updated_at=? WHERE id=?',
                     (encoded,moment,row['user_id']))
        conn.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',(moment,row['user_id']))
        log_event(conn,row['user_id'],'password_reset','ok')
    security.clear_cookie(response)
    return {'message':'Password updated. Sign in again.'}

@router.post('/change-password')
def change(body:Change,response:Response,user=Depends(cookie_mutation)):
    encoded=password_hash(body.new_password)
    with auth_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        limit(conn,'change',user['user_id'],5,900)
        row=conn.execute('SELECT password_hash FROM users WHERE id=?',(user['user_id'],)).fetchone()
        if not row or not identity.verify_password(row['password_hash'],body.current_password):
            conn.commit()
            raise HTTPException(401,'Invalid current password')
        moment=security.iso()
        conn.execute('UPDATE users SET password_hash=?,token_version=token_version+1,updated_at=? WHERE id=?',
                     (encoded,moment,user['user_id']))
        conn.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',(moment,user['user_id']))
        log_event(conn,user['user_id'],'password_change','ok')
    security.clear_cookie(response)
    return {'message':'Password updated. Sign in again.'}
