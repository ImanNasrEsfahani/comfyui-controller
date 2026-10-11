"""Phase05 user/account/admin UI APIs; fail-closed and never accepts browser tokens.

No content access, Worker operations, billing assertions, or destructive deletion.
All user identity comes from the Phase02 server-side cookie Session.
"""
from __future__ import annotations
import os
import hashlib
import secrets
import sqlite3
from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import db, security, identity_repository as identity
from .auth import ensure_mail_config, limit as auth_limit, reset_bucket
from .auth_mail import email_sender

router = APIRouter(prefix='/api',tags=['Account and administration'])


def ready():
    if os.getenv('ACCOUNT_UI_ENABLED','false').lower()!='true':
        raise HTTPException(503,'Account APIs are disabled')
    security.policy()
    with db.connect() as c:
        names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        needed={'account_audit_logs','account_email_changes','account_data_requests','user_preferences','user_roles'}
        if not needed <= names:
            raise HTTPException(503,'Phase05 migration is not applied')

# No auth/session route, admin token, or worker token can bypass current_user.
def current(user=Depends(security.require_active_user),_=Depends(ready)):
    return user

def mutation(request:Request,user=Depends(current)):
    security.require_csrf(request)
    return user

def admin(user=Depends(current)):
    if not {'admin','superadmin'}.intersection(user['roles']):
        raise HTTPException(403,'Admin role required')
    return user

def admin_mutation(request:Request,user=Depends(admin)):
    security.require_csrf(request)
    return user

def log(c,actor,action,subject_type,subject_id,outcome='ok',reason=None):
    # No email, prompt, filename, token, URL, IP or dynamic message enters audit.
    c.execute('''INSERT INTO account_audit_logs
      (id,actor_id,actor_type,action,subject_type,subject_id,outcome,reason_code,occurred_at)
      VALUES(?,?,?,?,?,?,?,?,?)''',
      (str(uuid4()),actor,'user',action,subject_type,subject_id,outcome,reason,security.iso()))

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Profile(Strict):
    display_name:str=Field(min_length=1,max_length=150)
class Pref(Strict):
    theme:str=Field(pattern='^(system|dark|light)$')
    locale:str=Field(pattern='^(fa|en)$')
    timezone:str=Field(max_length=64)
    default_model_id:str|None=Field(default=None,max_length=100)
    default_ratio:str|None=Field(default=None,max_length=30)
class EmailChange(Strict):
    new_email:str=Field(max_length=254)
    current_password:str
class EmailProof(Strict):
    token:str=Field(min_length=32,max_length=512)
class AdminStatus(Strict):
    status:str=Field(pattern='^(active|suspended)$')
    reason:str=Field(min_length=10,max_length=500)
class AdminRole(Strict):
    role:str=Field(pattern='^(user|admin)$')
    action:str=Field(pattern='^(grant|revoke)$')
    current_password:str
    reason:str=Field(min_length=10,max_length=500)
class Reason(Strict):
    reason:str=Field(min_length=10,max_length=500)


def profile(c,uid):
    row=c.execute('''SELECT id,display_name,email,email_verified_at,status,created_at,
     avatar_asset_id FROM users WHERE id=?''',(uid,)).fetchone()
    if row is None:raise HTTPException(404,'Account not found')
    obj=dict(row)
    # Avatar only if user-owned and available; no third-party storage URL.
    if obj['avatar_asset_id']:
        owned=c.execute('''SELECT 1 FROM input_assets WHERE asset_id=? AND owner_user_id=?
           AND ownership_state='verified' ''',(obj['avatar_asset_id'],uid)).fetchone()
        if not owned:obj['avatar_asset_id']=None
    obj['email_verified']=bool(obj.pop('email_verified_at'))
    return obj

@router.get('/users/me')
def get_me(user=Depends(current)):
    with db.connect() as c:return profile(c,user['user_id'])

@router.patch('/users/me')
def set_me(body:Profile,user=Depends(mutation)):
    name=body.display_name.strip()
    if not name:raise HTTPException(422,'Name required')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('UPDATE users SET display_name=?,updated_at=? WHERE id=? AND status=\'active\'',
                  (name,security.iso(),user['user_id']))
        log(c,user['user_id'],'profile.update','user',user['user_id'])
        return profile(c,user['user_id'])


def prefs(c,uid):
    row=c.execute('SELECT * FROM user_preferences WHERE user_id=?',(uid,)).fetchone()
    if row is None:
        return {'theme':'system','locale':'fa','timezone':'UTC','default_model_id':None,'default_ratio':None,
                'updated_at':None,'user_id':uid}
    d=dict(row);return {k:d.get(k) for k in ('user_id','theme','locale','timezone','default_model_id','default_ratio','updated_at')}

@router.get('/users/me/preferences')
def get_preferences(user=Depends(current)):
    with db.connect() as c:return prefs(c,user['user_id'])

@router.patch('/users/me/preferences')
def set_preferences(body:Pref,user=Depends(mutation)):
    try: ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError,ValueError):raise HTTPException(422,'Unknown timezone')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('''INSERT INTO user_preferences
          (user_id,theme,locale,timezone,default_model_id,default_ratio,updated_at)
          VALUES (?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
          theme=excluded.theme,locale=excluded.locale,timezone=excluded.timezone,
          default_model_id=excluded.default_model_id,default_ratio=excluded.default_ratio,
          updated_at=excluded.updated_at''',
          (user['user_id'],body.theme,body.locale,body.timezone,body.default_model_id,body.default_ratio,security.iso()))
        log(c,user['user_id'],'preferences.update','user',user['user_id'])
        return prefs(c,user['user_id'])

@router.post('/users/me/email-change',status_code=202)
def change_email(body:EmailChange,background:BackgroundTasks,user=Depends(mutation),mail=Depends(email_sender)):
    ensure_mail_config(mail)
    try:normalized=identity.normalized_email(body.new_email)
    except ValueError:raise HTTPException(422,'Invalid email')
    # Password step-up and same response for duplicate targets. No role or session upgrade.
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        auth_limit(c,'account_email_stepup',user['user_id'],5,900)
        row=c.execute('SELECT password_hash,email_normalized FROM users WHERE id=?',(user['user_id'],)).fetchone()
        if not row or not identity.verify_password(row['password_hash'],body.current_password):
            c.commit()  # Preserve failed step-up attempt counter.
            raise HTTPException(401,'Current password invalid')
        reset_bucket(c,'account_email_stepup',user['user_id'])
        recent=c.execute('SELECT requested_at FROM account_email_changes WHERE user_id=? ORDER BY requested_at DESC LIMIT 1',
                         (user['user_id'],)).fetchone()
        if recent:
            from datetime import datetime
            if (security.now()-datetime.fromisoformat(recent['requested_at'])).total_seconds()<600:
                raise HTTPException(429,'Email change cooldown active')
        taken=c.execute('SELECT id FROM users WHERE email_normalized=?',(normalized,)).fetchone()
        if taken or normalized==row['email_normalized']:
            log(c,user['user_id'],'email_change.request','user',user['user_id'],'denied','unavailable_target')
            return {'message':'If the new address is eligible, confirmation will be sent.'}
        raw=secrets.token_urlsafe(40)
        c.execute('''INSERT INTO account_email_changes
            (id,user_id,new_email,new_email_normalized,token_hash,expires_at,requested_at)
            VALUES (?,?,?,?,?,?,?)''',
            (str(uuid4()),user['user_id'],body.new_email.strip(),normalized,security.digest(raw),
             security.iso(security.now()+timedelta(minutes=30)),security.iso()))
        log(c,user['user_id'],'email_change.request','user',user['user_id'])
    # Use the existing redacted-background mailer; email proof URL never appears in an HTTP log.
    background.add_task(send_email_change,mail,body.new_email.strip(),raw)
    return {'message':'If the new address is eligible, confirmation will be sent.'}

def send_email_change(sender,recipient:str,raw:str):
    # Never include a secret in logs, error messages, or URL query strings.
    from urllib.parse import urlsplit
    import logging
    try:
        origin=os.environ['AUTH_PUBLIC_ORIGIN'].rstrip('/')
        sender.send(recipient,'Confirm your new email address',
                    f'Confirm the change within 30 minutes:\n{origin}/account/profile#email-change-token={raw}')
    except Exception:
        logging.getLogger(__name__).warning('Email change delivery failed; check private SMTP configuration')

@router.post('/users/me/verify-email-change')
def confirm_email(body:EmailProof,user=Depends(mutation)):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('''SELECT id,new_email,new_email_normalized FROM account_email_changes
          WHERE user_id=? AND token_hash=? AND consumed_at IS NULL AND expires_at>?''',
          (user['user_id'],security.digest(body.token),security.iso())).fetchone()
        if row is None:raise HTTPException(409,'Confirmation invalid or expired')
        conflict=c.execute('SELECT 1 FROM users WHERE email_normalized=? AND id!=?',
                           (row['new_email_normalized'],user['user_id'])).fetchone()
        if conflict:raise HTTPException(409,'Email change cannot be completed')
        instant=security.iso()
        c.execute('''UPDATE users SET email=?,email_normalized=?,email_verified_at=?,updated_at=?,
             token_version=token_version+1 WHERE id=?''',
             (row['new_email'],row['new_email_normalized'],instant,instant,user['user_id']))
        c.execute('UPDATE account_email_changes SET consumed_at=? WHERE user_id=? AND consumed_at IS NULL',
                  (instant,user['user_id']))
        c.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND id!=? AND revoked_at IS NULL',
                  (instant,user['user_id'],user['session_id']))
        log(c,user['user_id'],'email_change.confirm','user',user['user_id'])
        return {'message':'Email updated; other sessions revoked.'}

@router.get('/dashboard/summary')
def dashboard(user=Depends(current)):
    uid=user['user_id']
    with db.connect() as c:
        counts={r['state']:r['n'] for r in c.execute('''SELECT state,COUNT(*) n FROM jobs
         WHERE owner_user_id=? AND ownership_state='verified' AND hidden=0 GROUP BY state''',(uid,))}
        active={'pending','submitting','queued','waiting','preparing','processing','running','finalizing','cancel_requested'}
        recent=c.execute('''SELECT id,workflow_id,state,created_at FROM jobs
          WHERE owner_user_id=? AND ownership_state='verified' AND hidden=0
          ORDER BY created_at DESC,id DESC LIMIT 8''',(uid,)).fetchall()
        output_count=c.execute('''SELECT COUNT(*) FROM job_assets a JOIN jobs j ON a.job_id=j.id
          WHERE a.owner_user_id=? AND a.ownership_state='verified' AND a.status='available'
          AND j.owner_user_id=? AND j.ownership_state='verified' AND j.hidden=0
          AND (j.active_attempt_id IS NULL OR a.attempt_id=j.active_attempt_id)''',(uid,uid)).fetchone()[0]
        return {'counts':{'active':sum(counts.get(k,0) for k in active),
             'succeeded':counts.get('succeeded',0),'failed':sum(counts.get(k,0) for k in ('failed','submit_failed')),
             'outputs':output_count},'recent_jobs':[dict(r) for r in recent],
             'quota':{'status':'unavailable'},'gpu':{'status':'unknown'},'observed_at':security.iso()}

@router.get('/account/activity')
def activity(limit:int=30,user=Depends(current)):
    if not 1<=limit<=100:raise HTTPException(422,'Invalid limit')
    with db.connect() as c:
        rows=c.execute('''SELECT event_type,occurred_at,outcome FROM auth_events
          WHERE user_id=? ORDER BY occurred_at DESC,id DESC LIMIT ?''',(user['user_id'],limit)).fetchall()
        return {'items':[dict(r) for r in rows]}

@router.get('/account/data-summary')
def data_summary(user=Depends(current)):
    with db.connect() as c:
        rows=c.execute('''SELECT id,request_type,status,requested_at FROM account_data_requests
           WHERE user_id=? ORDER BY requested_at DESC LIMIT 20''',(user['user_id'],)).fetchall()
        return {'retention_policy':'not_approved','sharing_enabled':False,
                'requests':[dict(r) for r in rows]}

def new_data_request(kind,user):
    if os.getenv('ACCOUNT_REQUESTS_ENABLED','false').lower()!='true':
        raise HTTPException(503,'Data request workflow is not operational')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        rid=str(uuid4())
        c.execute('INSERT INTO account_data_requests(id,user_id,request_type,requested_at) VALUES (?,?,?,?)',
                  (rid,user['user_id'],kind,security.iso()))
        log(c,user['user_id'],'data_request.'+kind,'account_request',rid)
    return {'id':rid,'status':'pending_review','message':'Request received; no data has been deleted or exported.'}

@router.post('/account/export-request',status_code=202)
def export_request(user=Depends(mutation)):
    return new_data_request('export',user)
@router.post('/account/delete-request',status_code=202)
def delete_request(user=Depends(mutation)):
    return new_data_request('delete',user)


def admin_safe(row):
    d=dict(row)
    return {k:d[k] for k in ('id','email','display_name','status','email_verified_at','created_at','last_login_at')}

@router.get('/admin/summary')
def admin_summary(user=Depends(admin)):
    with db.connect() as c:
        users=c.execute('SELECT status,COUNT(*) n FROM users GROUP BY status').fetchall()
        queues=c.execute('SELECT state,COUNT(*) n FROM jobs GROUP BY state').fetchall()
        return {'users':{r['status']:r['n'] for r in users},'jobs_by_state':{r['state']:r['n'] for r in queues},
                'gpu':{'status':'unknown','observed_at':None},'cost':{'status':'unavailable'},
                'observed_at':security.iso(),'scope':'metadata_only'}

@router.get('/admin/users')
def users(limit:int=30,cursor:str|None=None,q:str='',status:str|None=None,user=Depends(admin)):
    if not 1<=limit<=100 or len(q)>100 or cursor and len(cursor)>100 or status and status not in {'active','pending','suspended','deletion_requested','deleted'}:
        raise HTTPException(422,'Invalid filters')
    clauses=[];args=[]
    if status:clauses.append('status=?');args.append(status)
    if q.strip():
        pattern='%'+q.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        clauses.append("(email_normalized LIKE ? ESCAPE '\\' OR display_name LIKE ? ESCAPE '\\')")
        args.extend([pattern.casefold(),pattern])
    if cursor:clauses.append('id>?');args.append(cursor)
    with db.connect() as c:
        rows=c.execute('''SELECT id,email,display_name,status,email_verified_at,created_at,last_login_at
         FROM users'''+(' WHERE '+' AND '.join(clauses) if clauses else '')+
         ' ORDER BY id LIMIT ?',args+[limit+1]).fetchall()
        results=[admin_safe(r) for r in rows[:limit]]
        return {'items':results,'next_cursor':results[-1]['id'] if len(rows)>limit and results else None}

@router.get('/admin/users/{uid}')
def admin_user(uid:str,user=Depends(admin)):
    with db.connect() as c:
        row=c.execute('''SELECT id,email,display_name,status,email_verified_at,created_at,last_login_at
           FROM users WHERE id=?''',(uid,)).fetchone()
        if row is None:raise HTTPException(404,'Account not found')
        return {'profile':admin_safe(row),
                'roles':[r[0] for r in c.execute('SELECT role_id FROM user_roles WHERE user_id=?',(uid,))],
                'sessions_active':c.execute('''SELECT COUNT(*) FROM sessions WHERE user_id=? AND revoked_at IS NULL
                  AND expires_at>? AND absolute_expires_at>?''',(uid,security.iso(),security.iso())).fetchone()[0],
                'usage':{'status':'unavailable'},'content_access':False}

@router.patch('/admin/users/{uid}')
def status_change(uid:str,body:AdminStatus,user=Depends(admin_mutation)):
    actor=user['user_id']
    if actor==uid:raise HTTPException(409,'You cannot change your own administrative status')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        target=c.execute('SELECT status,email_verified_at FROM users WHERE id=?',(uid,)).fetchone()
        if not target:raise HTTPException(404,'Account not found')
        roles={r[0] for r in c.execute('SELECT role_id FROM user_roles WHERE user_id=?',(uid,))}
        if {'admin','superadmin'} & roles and 'superadmin' not in user['roles']:
            raise HTTPException(403,'Only superadmin may modify administrative accounts')
        if {'admin','superadmin'} & roles and body.status=='suspended':
            remaining=c.execute('''SELECT COUNT(*) FROM users u JOIN user_roles r ON r.user_id=u.id
              WHERE r.role_id IN ('admin','superadmin') AND u.status='active' AND u.id!=?''',(uid,)).fetchone()[0]
            if remaining==0:raise HTTPException(409,'Last active administrator cannot be suspended')
        if body.status=='active' and not target['email_verified_at']:
            raise HTTPException(409,'Unverified account cannot be activated')
        updated=c.execute('''UPDATE users SET status=?,updated_at=?,token_version=token_version+1 WHERE id=? AND status=?''',
                         (body.status,security.iso(),uid,target['status']))
        if not updated.rowcount:raise HTTPException(409,'State changed concurrently')
        if body.status=='suspended':
            c.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',(security.iso(),uid))
        log(c,actor,'user.status_'+body.status,'user',uid,reason='reason_sha256:'+hashlib.sha256(body.reason.strip().encode()).hexdigest()[:24])
    return {'status':body.status,'sessions_revoked':body.status=='suspended'}

@router.post('/admin/users/{uid}/role')
def role_change(uid:str,body:AdminRole,user=Depends(admin_mutation)):
    if 'superadmin' not in user['roles']:
        raise HTTPException(403,'Verified superadmin required')
    if uid==user['user_id']:raise HTTPException(409,'Cannot change your own role')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        auth_limit(c,'admin_role_stepup',user['user_id'],5,900)
        actor=c.execute('SELECT password_hash FROM users WHERE id=?',(user['user_id'],)).fetchone()
        if not actor or not identity.verify_password(actor['password_hash'],body.current_password):
            c.commit()  # Failed attempts persist, then 429 backoff.
            raise HTTPException(401,'Step-up authentication failed')
        reset_bucket(c,'admin_role_stepup',user['user_id'])
        target=c.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone()
        if not target:raise HTTPException(404,'Account not found')
        if body.role=='admin' and body.action=='revoke':
            count=c.execute('''SELECT COUNT(*) FROM users u JOIN user_roles r ON r.user_id=u.id
                WHERE r.role_id IN ('admin','superadmin') AND u.status='active' AND u.id!=?''',(uid,)).fetchone()[0]
            if count==0:raise HTTPException(409,'Last administrator cannot be demoted')
        if body.action=='grant':
            c.execute('INSERT OR IGNORE INTO user_roles(user_id,role_id,granted_by,granted_at) VALUES (?,?,?,?)',
                      (uid,body.role,user['user_id'],security.iso()))
        else:
            c.execute('DELETE FROM user_roles WHERE user_id=? AND role_id=?',(uid,body.role))
        c.execute('UPDATE users SET token_version=token_version+1 WHERE id=?',(uid,))
        c.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',(security.iso(),uid))
        log(c,user['user_id'],'role.'+body.action+'_'+body.role,'user',uid,reason='reason_sha256:'+hashlib.sha256(body.reason.strip().encode()).hexdigest()[:24])
    return {'accepted':True,'sessions_revoked':True}

@router.get('/admin/audit-logs')
def audit_logs(limit:int=40,cursor:str|None=None,action:str|None=None,user=Depends(admin)):
    if not 1<=limit<=100 or cursor and len(cursor)>250 or action and len(action)>80:
        raise HTTPException(422,'Invalid filters')
    clauses=[];args=[]
    if cursor:
        parts=cursor.split('|',1)
        if len(parts)!=2:raise HTTPException(422,'Invalid cursor')
        clauses.append('(occurred_at<? OR (occurred_at=? AND id<?))');args.extend([parts[0],parts[0],parts[1]])
    if action:clauses.append('action=?');args.append(action)
    with db.connect() as c:
        rows=c.execute('''SELECT id,actor_id,action,subject_type,subject_id,outcome,reason_code,occurred_at
         FROM account_audit_logs'''+(' WHERE '+' AND '.join(clauses) if clauses else '')+
         ' ORDER BY occurred_at DESC,id DESC LIMIT ?',args+[limit+1]).fetchall()
        items=[dict(r) for r in rows[:limit]]
        last=items[-1] if items else None
        return {'items':items,'next_cursor':f'{last["occurred_at"]}|{last["id"]}' if len(rows)>limit and last else None}
