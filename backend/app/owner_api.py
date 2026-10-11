"""Phase03 fail-closed, owner-only HTTP API, inserted BEFORE the legacy routes.

This API is an explicit experimental gate. It never reuses X-Internal-Token or
X-Worker-Token. No public account activation or real GPU action is authorized.
"""
from __future__ import annotations
import io
import json
import os
import re
import warnings
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image, UnidentifiedImageError

from . import db, security, storage, owner_repository as owners
from .config import settings


def enable():
    if os.getenv('OWNER_ISOLATION_ENABLED','false').lower()!='true':
        raise HTTPException(503,'Owner isolation is disabled')
    security.policy()
    with db.connect() as conn:
        try: owners.require_schema(conn)
        except owners.MissingOwnerSchema as exc:raise HTTPException(503,str(exc)) from exc

router=APIRouter(prefix='/api',tags=['Owner-scoped API'],dependencies=[Depends(enable)])
user_dep=Depends(security.require_active_user)


def denial():
    raise HTTPException(404,'Resource not found')


def output(row,c,uid):
    """No long-lived URL, storage key, service credentials, lease or foreign asset."""
    r=dict(row)
    for k in ('lease_token_hash','worker_id','request_hash','request_json','snapshot_json',
              'variables_json','output_json','error_text','owner','salad_job_id'):
        r.pop(k,None)
    for col,newcol in (('snapshot_json','snapshot'),('variables_json','variables')):
        try:r[newcol]=json.loads(row[col]) if row[col] else None
        except (TypeError,ValueError):r[newcol]=None
    r['assets']=[{k:v for k,v in a.items() if k not in {'storage_key'}} | {
        'download_url':f'/api/jobs/{row["id"]}/assets/{a["asset_id"]}/download'}
        for a in owners.job_assets(c,uid,row['id'])]
    r['output_summary']={'available':len(r['assets'])}
    return r


def need_job(c,uid,jid):
    row=owners.job(c,uid,jid)
    if row is None:denial()
    return row


@router.get('/jobs')
def jobs(limit:int=50,user=user_dep):
    with db.connect() as c:
        rows,_,_=owners.list_jobs(c,user['user_id'],limit=min(max(limit,1),100))
        return [output(row,c,user['user_id']) for row in rows]


@router.get('/jobs/history')
def history(limit:int=24,state:str|None=None,workflow_id:str|None=None,
            created_after:str|None=None,created_before:str|None=None,q:str|None=None,
            cursor:str|None=None,user=user_dep):
    if limit<1 or limit>100 or q and len(q)>160:raise HTTPException(422,'Invalid history filter')
    # Opaque cursor encodes no identities and filters by the authenticated user.
    at=jid=None
    if cursor:
        import base64
        try:
            d=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))
            at,jid=d['at'],d['id']
            if not isinstance(at,str) or not isinstance(jid,str) or len(at)>80 or len(jid)>80:raise ValueError()
        except (ValueError,KeyError,TypeError):raise HTTPException(422,'Invalid cursor')
    with db.connect() as c:
        rows,total,has_more=owners.list_jobs(c,user['user_id'],limit=limit,state=state,workflow_id=workflow_id,
            query=q,after=created_after,before=created_before,cursor_at=at,cursor_id=jid)
        next_cursor=None
        if has_more and rows:
            import base64
            blob=json.dumps({'at':rows[-1]['created_at'],'id':rows[-1]['id']},separators=(',',':'))
            next_cursor=base64.urlsafe_b64encode(blob.encode()).decode().rstrip('=')
        return {'items':[output(row,c,user['user_id']) for row in rows],
                'count':len(rows),'total':total,'next_cursor':next_cursor}


@router.get('/job-requests/{client_request_id}')
def request_lookup(client_request_id:str,user=user_dep):
    with db.connect() as c:
        row=owners.job_for_request(c,user['user_id'],client_request_id)
        if row is None:denial()
        return output(row,c,user['user_id'])


@router.get('/job-comparison')
def compare(first_id:str,second_id:str,user=user_dep):
    if first_id==second_id:raise HTTPException(422,'Choose different Jobs')
    with db.connect() as c:
        first=owners.job(c,user['user_id'],first_id)
        second=owners.job(c,user['user_id'],second_id)
        if first is None or second is None:denial()
        safe_keys=('id','workflow_id','state','created_at','started_at','finished_at')
        return {'first':{k:first[k] for k in safe_keys},'second':{k:second[k] for k in safe_keys}}


@router.get('/assets')
def assets(limit:int=50,user=user_dep):
    with db.connect() as c:
        return {'items':owners.assets_page(c,user['user_id'],limit)}


@router.get('/assets/{asset_id}')
def asset_detail(asset_id:str,user=user_dep):
    with db.connect() as c:
        a=owners.asset(c,user['user_id'],asset_id)
        if a is None:denial()
        return {k:v for k,v in a.items() if k!='storage_key'}


@router.post('/assets/{asset_id}/download-ticket')
def asset_ticket(asset_id:str,request:Request,user=user_dep):
    security.require_csrf(request)
    with db.connect() as c:
        a=owners.asset(c,user['user_id'],asset_id)
        if a is None:denial()
        key=a['storage_key']
    # URL never returned before direct asset authorization. Signed bearer
    # remains valid until expiry: do not log, cache or persist this URL.
    ttl=min(120,max(1,settings.r2_presign_ttl_seconds))
    return {'url':storage.presign_get(key,ttl=ttl),'expires_in':ttl}


@router.post('/assets/{asset_id}/use-as-input')
def use_as_input(asset_id:str,request:Request,user=user_dep):
    security.require_csrf(request)
    with db.connect() as c:
        if owners.asset(c,user['user_id'],asset_id) is None:denial()
    return {'asset_id':asset_id,'allowed':True}  # No GPU dispatch performed


@router.get('/jobs/{local_id}/assets/{asset_id}/download')
def download(local_id:str,asset_id:str,user=user_dep):
    with db.connect() as c:
        need_job(c,user['user_id'],local_id)
        a=owners.asset(c,user['user_id'],asset_id)
        if not a or a['kind']!='output' or a['job_id']!=local_id:denial()
        key=a['storage_key'];content_type=a['mime_type'] or 'application/octet-stream'
    if not key.startswith(f'outputs/{local_id}/') or '..' in key.split('/'):
        denial()
    try:obj=storage.get_object(key)
    except Exception:raise HTTPException(404,'Output no longer available')
    name=re.sub(r'[^A-Za-z0-9._-]','_',key.rsplit('/',1)[-1])[:128] or 'output'
    def chunks():
        try:yield from obj['Body'].iter_chunks(chunk_size=1024*1024)
        finally:obj['Body'].close()
    headers={'Content-Disposition':f'attachment; filename="{name}"','Cache-Control':'private, no-store',
             'X-Content-Type-Options':'nosniff'}
    if isinstance(obj.get('ContentLength'),int) and obj['ContentLength']>=0:
        headers['Content-Length']=str(obj['ContentLength'])
    return StreamingResponse(chunks(),headers=headers,media_type=content_type)


@router.get('/jobs/{local_id}/images')
def images(local_id:str,user=user_dep):
    with db.connect() as c:
        need_job(c,user['user_id'],local_id)
        items=owners.job_assets(c,user['user_id'],local_id)
        safe=[{k:v for k,v in a.items() if k!='storage_key'} | {
             'download_url':f'/api/jobs/{local_id}/assets/{a["asset_id"]}/download'} for a in items]
        return {'images':[a for a in safe if a.get('media_type')=='image'],'assets':safe}


@router.get('/jobs/{local_id}/draft')
def draft(local_id:str,user=user_dep):
    with db.connect() as c:
        row=need_job(c,user['user_id'],local_id)
        try:values=json.loads(row['variables_json']) if row['variables_json'] else None
        except ValueError:values=None
        if values is None:raise HTTPException(409,'Legacy draft cannot be reconstructed safely')
        snapshot=json.loads(row['snapshot_json']) if row['snapshot_json'] else {}
        return {'workflow_id':row['workflow_id'],'variables':values,
                'seed_mode':snapshot.get('seed_mode','fixed'),'legacy':False}


@router.post('/jobs/{local_id}/cancel')
def cancel(local_id:str,request:Request,user=user_dep):
    security.require_csrf(request)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        result=owners.cancel_direct(c,user['user_id'],local_id)
        if result is None:denial()
        if 'error' in result:raise HTTPException(409,'This job cannot be cancelled')
        return result


@router.delete('/jobs/{local_id}',status_code=204)
def hide(local_id:str,request:Request,user=user_dep):
    security.require_csrf(request)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if owners.job(c,user['user_id'],local_id) is None:denial()
        if not owners.hide(c,user['user_id'],local_id):
            raise HTTPException(409,'Cancel or finish active Job before hiding')


@router.post('/jobs/{local_id}/retry')
def retry(local_id:str,request:Request,user=user_dep):
    security.require_csrf(request)
    with db.connect() as c:
        need_job(c,user['user_id'],local_id)
    # An unscoped legacy retry or remote resubmission can make duplicate GPU
    # work. Until a fully owner-transactional retry is reviewed, fail closed.
    raise HTTPException(503,'Owner-safe retry is not yet enabled')


@router.post('/jobs')
def generate(request:Request,user=user_dep):
    security.require_csrf(request)
    # Legacy db.create_job() still has global request-key lookup and may race
    # Worker claim before owner is saved. Never submit an ownerless GPU Job.
    raise HTTPException(503,'Owner-safe job submission is not yet enabled')


@router.post('/uploads')
def upload(request:Request,file:UploadFile=File(...),user=user_dep):
    security.require_csrf(request)
    limit=max(1,settings.max_upload_mb)*1024*1024
    content=file.file.read(limit+1)
    if not content or len(content)>limit:
        raise HTTPException(413,'Image missing or exceeds size limit')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as p:
                fmt=p.format
                if fmt not in {'PNG','JPEG','WEBP','GIF'} or p.width*p.height>40_000_000:
                    raise ValueError('Unsupported image')
                p.verify()
            with Image.open(io.BytesIO(content)) as p:
                p.load();width,height=p.size
    except (OSError,UnidentifiedImageError,ValueError,Image.DecompressionBombWarning,Image.DecompressionBombError):
        raise HTTPException(422,'Invalid image content')
    mimetype={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp','GIF':'image/gif'}[fmt]
    if file.content_type and file.content_type not in (mimetype,'application/octet-stream'):
        raise HTTPException(422,'Content type mismatch')
    aid=str(uuid4())
    ext={'PNG':'png','JPEG':'jpg','WEBP':'webp','GIF':'gif'}[fmt]
    key=f'inputs/{aid}/original.{ext}'
    # R2 network call is outside SQLite lock. If DB commit fails, the random
    # object becomes quarantined/unclaimed; it is never made public.
    storage.upload_fileobj(io.BytesIO(content),key,mimetype)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('''INSERT INTO input_assets(asset_id,storage_key,mime_type,size_bytes,
          width,height,created_at,owner_user_id,ownership_state)
          VALUES (?,?,?,?,?,?,?,?,?)''',
          (aid,key,mimetype,len(content),width,height,db.utcnow(),user['user_id'],'verified'))
    return {'asset_id':aid,'mime_type':mimetype,'width':width,'height':height,
            'size_bytes':len(content),'url':storage.presign_get(key,ttl=min(120,settings.r2_presign_ttl_seconds))}


@router.get('/jobs/{local_id}')
def job_detail(local_id:str,user=user_dep):
    with db.connect() as c:
        row=need_job(c,user['user_id'],local_id)
        return output(row,c,user['user_id'])


@router.get('/user/instance-status')
def aggregate_status(user=user_dep):
    # User never sees Salad IDs, image digests, private group settings.
    return {'readiness':'unknown','estimated_wait_seconds':None}
