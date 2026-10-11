"""Phase03 SQL-enforced owner isolation. Never accept an identity from user input.

Existing legacy tables are preserved. Only verified rows are readable. Ownerless
legacy records require the explicit Phase01 out-of-band backfill procedure.
"""
from __future__ import annotations
import sqlite3
from typing import Any
from . import db


class MissingOwnerSchema(RuntimeError):
    pass


def require_schema(c: sqlite3.Connection) -> None:
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'users', 'jobs', 'input_assets', 'job_assets', 'sessions', 'schema_migrations'} <= tables:
        raise MissingOwnerSchema('Phase01 identity database migration is missing')
    for name in ('jobs', 'input_assets', 'job_assets'):
        columns = {row['name'] for row in c.execute(f'PRAGMA table_info({name})')}
        if not {'owner_user_id', 'ownership_state'} <= columns:
            raise MissingOwnerSchema('Verified owner columns are missing')


def job(c: sqlite3.Connection, uid: str, jid: str):
    return c.execute("""SELECT * FROM jobs WHERE id=? AND owner_user_id=?
        AND ownership_state='verified' AND hidden=0""", (jid,uid)).fetchone()


def job_for_request(c:sqlite3.Connection,uid:str,client_id:str):
    return c.execute("""SELECT * FROM jobs WHERE owner_user_id=?
        AND ownership_state='verified' AND hidden=0 AND client_request_id=?""",(uid,client_id)).fetchone()


def list_jobs(c,uid,*,limit=50,state=None,workflow_id=None,query=None,after=None,before=None,cursor_at=None,cursor_id=None):
    if not (1 <= limit <= 100):
        raise ValueError('Invalid page size')
    conditions=["owner_user_id=?", "ownership_state='verified'",'hidden=0']
    args: list[Any]=[uid]
    if state:
        conditions.append('state=?');args.append(state)
    if workflow_id:
        conditions.append('workflow_id=?');args.append(workflow_id)
    if after:
        conditions.append('created_at>=?');args.append(after)
    if before:
        conditions.append('created_at<=?');args.append(before)
    if query:
        esc=query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        conditions.append("(COALESCE(snapshot_json,'') || COALESCE(variables_json,'') || COALESCE(request_json,'')) LIKE ? ESCAPE '\\'")
        args.append('%'+esc+'%')
    where=' AND '.join(conditions)
    total=c.execute('SELECT count(*) FROM jobs WHERE '+where,args).fetchone()[0]
    if cursor_at is not None and cursor_id is not None:
        conditions.append('(created_at<? OR (created_at=? AND id<?))')
        args.extend([cursor_at,cursor_at,cursor_id])
    rows=c.execute('SELECT * FROM jobs WHERE '+' AND '.join(conditions)+
                   ' ORDER BY created_at DESC,id DESC LIMIT ?',args+[limit+1]).fetchall()
    return rows[:limit],total,len(rows)>limit


def asset(c,uid,aid):
    # Both direct owner and parent job ownership are checked, NEVER parent only.
    a=c.execute("""SELECT i.asset_id,i.storage_key,i.mime_type,i.width,i.height,
        i.size_bytes,i.created_at,'input' AS kind,NULL AS job_id
        FROM input_assets i WHERE i.asset_id=? AND i.owner_user_id=?
        AND i.ownership_state='verified'""",(aid,uid)).fetchone()
    if a:return dict(a)
    a=c.execute("""SELECT a.asset_id,a.storage_key,a.mime_type,a.width,a.height,
        a.size_bytes,a.created_at,'output' AS kind,a.job_id
        FROM job_assets a INNER JOIN jobs j ON j.id=a.job_id
        WHERE a.asset_id=? AND a.owner_user_id=? AND a.ownership_state='verified'
        AND a.status='available' AND j.owner_user_id=?
        AND j.ownership_state='verified' AND j.hidden=0
        AND (j.active_attempt_id IS NULL OR a.attempt_id=j.active_attempt_id)""",(aid,uid,uid)).fetchone()
    return dict(a) if a else None


def job_assets(c,uid,jid):
    return [dict(r) for r in c.execute("""SELECT a.asset_id,a.storage_key,a.mime_type,
        a.media_type,a.width,a.height,a.size_bytes,a.created_at,a.status,a.attempt_id
        FROM job_assets a JOIN jobs j ON a.job_id=j.id
        WHERE j.id=? AND j.owner_user_id=? AND j.ownership_state='verified'
        AND j.hidden=0 AND a.owner_user_id=? AND a.ownership_state='verified'
        AND a.status='available' AND (j.active_attempt_id IS NULL OR a.attempt_id=j.active_attempt_id)
        ORDER BY a.created_at DESC""",(jid,uid,uid)).fetchall()]


def assets_page(c,uid,limit=50):
    if not 1<=limit<=100:raise ValueError('Invalid page size')
    inputs=c.execute("""SELECT i.asset_id,i.mime_type,i.width,i.height,
        i.created_at,'input' AS kind FROM input_assets i
        WHERE i.owner_user_id=? AND i.ownership_state='verified'
        ORDER BY i.created_at DESC LIMIT ?""",(uid,limit)).fetchall()
    outputs=c.execute("""SELECT a.asset_id,a.mime_type,a.width,a.height,
        a.created_at,'output' AS kind FROM job_assets a JOIN jobs j ON j.id=a.job_id
        WHERE a.owner_user_id=? AND a.ownership_state='verified' AND a.status='available'
        AND j.owner_user_id=? AND j.ownership_state='verified' AND j.hidden=0
        AND (j.active_attempt_id IS NULL OR a.attempt_id=j.active_attempt_id)
        ORDER BY a.created_at DESC LIMIT ?""",(uid,uid,limit)).fetchall()
    return sorted([dict(x) for x in inputs]+[dict(x) for x in outputs],
                  key=lambda a:(a['created_at'],a['asset_id']),reverse=True)[:limit]


def hide(c,uid,jid):
    # Predicate is included in the mutation, not only in an earlier check.
    return c.execute("""UPDATE jobs SET hidden=1,updated_at=? WHERE id=? AND owner_user_id=?
        AND ownership_state='verified' AND hidden=0
        AND state NOT IN ('pending','submitting','queued','waiting','preparing','running','processing','finalizing','cancel_requested')""",
        (db.utcnow(),jid,uid)).rowcount == 1


def cancel_direct(c,uid,jid):
    """DB-atomic cancellation/interrupt request; worker already fences the lease."""
    row=job(c,uid,jid)
    if not row:return None
    if row['execution_mode']!='direct':return {'error':'unsupported'}
    state=row['state'];instant=db.utcnow()
    if state=='pending':
        cursor=c.execute("""UPDATE jobs SET state='cancelled',finished_at=?,updated_at=?
          WHERE id=? AND owner_user_id=? AND ownership_state='verified' AND state='pending'""",
          (instant,instant,jid,uid))
        return {'state':'cancelled'} if cursor.rowcount else {'error':'conflict'}
    if state=='running':
        cursor=c.execute("""UPDATE jobs SET state='cancel_requested',updated_at=?
          WHERE id=? AND owner_user_id=? AND ownership_state='verified' AND state='running'""",
          (instant,jid,uid))
        return {'state':'cancel_requested'} if cursor.rowcount else {'error':'conflict'}
    if state in {'cancel_requested','cancelled'}:return {'state':state}
    return {'error':'conflict'}


def assert_refs(c,uid,items):
    """Validate reference IDs before any GPU dispatch. Call in write transaction."""
    result=[]
    for item in items:
        a=asset(c,uid,item)
        if a is None:raise PermissionError('Reference not found')
        result.append(a)
    return result
