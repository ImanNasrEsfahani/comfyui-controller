"""Private SCAIL-2 character-replacement jobs, separate from Qwen Direct Queue.

This is an opt-in, bounded, owner-scoped lane with independent leases. It does
not bypass the current application's video-generation 503 runtime gate.
Only the dedicated SCAIL-2 worker can claim, heartbeat, or finish its jobs.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from . import db, security, storage
from .config import settings

router = APIRouter(prefix='/api/v2/character-replace', tags=['SCAIL-2 replacement'])
user = Depends(security.require_active_user)
WORKER_HEADER = 'X-Character-Worker-Token'
MAX_VIDEO_BYTES = 90 * 1024 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_SECONDS = 10.0  # Version 1: 2 x 81-frame chunks at 16fps
LEASE_SECONDS = 120
MAX_ATTEMPTS = 2
MAX_PENDING_PER_USER = 3
MAX_PENDING_GLOBAL = 25
ALLOWED_QUALITY = {'quality', 'fast'}
ERROR_STATUSES = {'failed', 'stalled', 'cancelled'}
ACTIVE = {'preparing', 'running', 'uploading', 'cancel_requested'}


def now():
    return datetime.now(timezone.utc).isoformat()


def _enabled():
    if os.getenv('CHARACTER_REPLACE_ENABLED', 'false').lower() != 'true':
        raise HTTPException(503, 'Character replacement is disabled')
    with db.connect() as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'cr_assets', 'cr_jobs', 'cr_runtime', 'cr_upload_sessions'}.issubset(tables):
        raise HTTPException(503, 'Run scripts/migrate_scail2.py first')


def _user(actor=user):
    _enabled()
    return actor


def _mutation(request: Request, actor=Depends(_user)):
    security.require_csrf(request)
    return actor


def _worker(request: Request):
    _enabled()
    expected = os.getenv('CHARACTER_REPLACE_WORKER_TOKEN', '')
    given = request.headers.get(WORKER_HEADER, '')
    if len(expected) < 32 or not hmac.compare_digest(expected, given):
        raise HTTPException(401, 'Invalid worker credential')


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _probe(path: Path):
    try:
        p = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                           capture_output=True, text=True, timeout=20, check=True)
        data = json.loads(p.stdout)
        video = next(s for s in data['streams'] if s.get('codec_type') == 'video')
        fmt = data['format']
        width, height = int(video['width']), int(video['height'])
        duration = float(fmt.get('duration') or video.get('duration'))
        rate = video.get('avg_frame_rate', '0/1').split('/')
        fps = float(rate[0]) / float(rate[1]) if len(rate) == 2 and float(rate[1]) else 0
        if not (0 < duration <= MAX_SECONDS and 64 <= width <= 2160 and 64 <= height <= 2160
                and width % 2 == 0 and height % 2 == 0 and 1 <= fps <= 60):
            raise ValueError('Video duration, FPS, or dimensions are outside the preview limits')
        if video.get('codec_name') not in {'h264', 'hevc', 'vp8', 'vp9', 'av1'}:
            raise ValueError('Unsupported video codec')
        return {'duration': round(duration, 3), 'width': width, 'height': height, 'fps': round(fps, 3)}
    except (subprocess.TimeoutExpired, FileNotFoundError, KeyError, StopIteration, ValueError,
            TypeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise HTTPException(422, 'Unsupported or corrupt video. Use a short MP4/WebM with an ordinary video codec.') from exc


def _asset(c, actor, asset_id, kind):
    row = c.execute('SELECT * FROM cr_assets WHERE id=? AND owner_id=? AND kind=?',
                    (asset_id, actor['user_id'], kind)).fetchone()
    if not row:
        raise HTTPException(404, 'Private asset not found')
    return dict(row)


def _job(c, actor, job_id):
    row = c.execute('SELECT * FROM cr_jobs WHERE id=? AND owner_id=?', (job_id, actor['user_id'])).fetchone()
    if not row:
        raise HTTPException(404, 'Private job not found')
    return dict(row)


def _mark_expired(c):
    # No backend consumer may show a dead lease as running indefinitely.
    c.execute("""UPDATE cr_jobs SET state='stalled',lease_hash=NULL,lease_until=NULL,
        error='Worker lease lost; operator must verify old execution stopped before retry',updated_at=?
        WHERE state IN ('preparing','running','uploading','cancel_requested')
          AND lease_until IS NOT NULL AND lease_until < ?""",(now(),time.time()))


def _public(row):
    return {k: row[k] for k in ('id', 'state', 'quality', 'steps', 'seed', 'source_video_id',
            'reference_image_id', 'created_at', 'updated_at', 'started_at', 'finished_at',
            'error', 'preserve_audio', 'attempts') if k in row}


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class JobRequest(Strict):
    source_video_id: str = Field(pattern=r'^[a-f0-9-]{36}$')
    reference_image_id: str = Field(pattern=r'^[a-f0-9-]{36}$')
    client_request_id: str = Field(min_length=8, max_length=96, pattern=r'^[A-Za-z0-9._:-]+$')
    prompt: str = Field(default='', max_length=1500)
    detect_prompt: str = Field(default='a person', min_length=2, max_length=100)
    quality: str = Field(default='quality', pattern='^(quality|fast)$')
    steps: int = Field(default=24, ge=4, le=32)
    seed: int = Field(default=1, ge=0, le=2**63-1)
    preserve_audio: bool = True
    confirmed_rights: bool


class RecoverRequest(Strict):
    confirm_worker_stopped: bool


class WorkerHello(Strict):
    generation: str = Field(min_length=16, max_length=96, pattern=r'^[A-Za-z0-9_-]+$')
    ready: bool


class WorkerEvent(Strict):
    job_id: str
    lease_token: str
    state: str = Field(pattern='^(preparing|running|uploading|cancelled|failed|succeeded)$')
    error: str = Field(default='', max_length=500)


class Heartbeat(Strict):
    job_id: str
    lease_token: str


@router.get('/config')
def config(actor=Depends(_user)):
    with db.connect() as c:
        worker = c.execute('SELECT seen_at,ready FROM cr_runtime WHERE id=1').fetchone()
    fresh = bool(worker and int(worker['ready']) == 1 and time.time() - float(worker['seen_at']) < 65)
    return {'enabled': True, 'model': 'SCAIL-2 Wan2.1 14B FP16', 'max_seconds': None,
            'legacy_upload_max_seconds': MAX_SECONDS,
            'max_video_mb': MAX_VIDEO_BYTES // 1048576, 'max_reference_mb': MAX_IMAGE_BYTES // 1048576,
            'direct_upload':True,'max_source_gib':int(os.getenv('CHARACTER_REPLACE_MAX_VIDEO_GIB','20')),
            'long_video_mode':'automatic-window-beta',
            'quality_profiles': [{'id': 'quality', 'steps': 24, 'distill': False, 'dpo_lora': True},
                                 {'id': 'fast', 'steps': 4, 'distill': True, 'dpo_lora': True}],
            'limits': 'One detected person; video is sampled at 16 fps. Multiple people are not reliably selectable in V1.',
            'worker_ready': fresh, 'worker_status': 'Ready heartbeat observed' if fresh else 'Worker not connected/ready; queued jobs need a manually active Salad replica'}


@router.post('/assets/{kind}', status_code=201)
async def upload(kind: str, request: Request, file: UploadFile = File(...), actor=Depends(_mutation)):
    if kind not in ('video', 'reference'):
        raise HTTPException(404, 'Unknown asset type')
    limit = MAX_VIDEO_BYTES if kind == 'video' else MAX_IMAGE_BYTES
    tmp = tempfile.NamedTemporaryFile(delete=False)
    path = Path(tmp.name)
    size = 0
    try:
        with tmp:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, 'File exceeds allowed size')
                tmp.write(chunk)
        if size < 64:
            raise HTTPException(422, 'File is too small')
        if kind == 'video':
            with path.open('rb') as reader:
                magic = reader.read(16)
            if b'ftyp' in magic[4:16]:
                mime, extension = 'video/mp4', 'mp4'
            elif magic.startswith(b'\x1a\x45\xdf\xa3'):
                mime, extension = 'video/webm', 'webm'
            else:
                raise HTTPException(422, 'Only MP4 or WebM supported')
            meta = _probe(path)
        else:
            try:
                with Image.open(path) as picture:
                    if picture.format not in ('PNG', 'JPEG', 'WEBP'):
                        raise ValueError('Unsupported image format')
                    picture.verify()
                with Image.open(path) as picture:
                    picture = ImageOps.exif_transpose(picture)
                    if picture.width * picture.height > 24_000_000:
                        raise ValueError('Image is too large')
                    meta = {'width': picture.width, 'height': picture.height, 'duration': None, 'fps': None}
                with Image.open(path) as picture:
                    mime, extension = {'PNG': ('image/png', 'png'), 'JPEG': ('image/jpeg', 'jpg'),
                                       'WEBP': ('image/webp', 'webp')}[picture.format]
            except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError) as exc:
                raise HTTPException(422, 'Corrupt or unsupported reference image') from exc
        asset_id = str(uuid4())
        key = f'inputs/character-replace/{actor["user_id"]}/{asset_id}.{extension}'
        with path.open('rb') as source:
            storage.upload_fileobj(source, key, mime)
        head = storage.client().head_object(Bucket=settings.r2_bucket, Key=key)
        if int(head.get('ContentLength', 0)) != size or head.get('ContentType') not in {mime,'application/octet-stream'}:
            raise HTTPException(503, 'Storage verification failed')
        with db.connect() as c:
            c.execute('''INSERT INTO cr_assets(id,owner_id,kind,r2_key,mime,size_bytes,width,height,duration,fps,created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                      (asset_id,actor['user_id'],kind,key,mime,size,meta['width'],meta['height'],
                       meta['duration'],meta['fps'],now()))
        return {'asset_id': asset_id, 'kind': kind, 'size_bytes': size, **meta}
    finally:
        path.unlink(missing_ok=True)
        await file.close()


@router.post('/jobs', status_code=202)
def submit(body: JobRequest, actor=Depends(_mutation)):
    if not body.confirmed_rights:
        raise HTTPException(422, 'Confirm rights and participant consent before submitting')
    if body.quality == 'fast' and not 4 <= body.steps <= 8:
        raise HTTPException(422, 'Fast mode supports 4 to 8 steps')
    if body.quality == 'quality' and not 16 <= body.steps <= 32:
        raise HTTPException(422, 'Quality mode supports 16 to 32 steps')
    data = body.model_dump(exclude={'client_request_id', 'confirmed_rights'})
    fingerprint = _hash(json.dumps(data,sort_keys=True,ensure_ascii=False))
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT * FROM cr_jobs WHERE owner_id=? AND client_key=?',
                        (actor['user_id'],body.client_request_id)).fetchone()
        if old:
            if old['fingerprint'] != fingerprint:
                raise HTTPException(409, 'Idempotency key reused for another request')
            return _public(dict(old))
        pending_states=('queued','preparing','running','uploading','cancel_requested','stalled')
        by_user=c.execute('SELECT COUNT(*) FROM cr_jobs WHERE owner_id=? AND state IN ('+
                          ','.join('?' for _ in pending_states)+')',
                          (actor['user_id'],*pending_states)).fetchone()[0]
        global_pending=c.execute('SELECT COUNT(*) FROM cr_jobs WHERE state IN ('+
                                 ','.join('?' for _ in pending_states)+')', pending_states).fetchone()[0]
        if by_user>=MAX_PENDING_PER_USER:
            raise HTTPException(429,'At most three pending character videos per account')
        if global_pending>=MAX_PENDING_GLOBAL:
            raise HTTPException(429,'Character video queue is full; retry after a job finishes')
        _asset(c,actor,body.source_video_id,'video')
        _asset(c,actor,body.reference_image_id,'reference')
        jid = str(uuid4()); created = now()
        c.execute('''INSERT INTO cr_jobs
          (id,owner_id,source_video_id,reference_image_id,client_key,fingerprint,prompt,detect_prompt,quality,
           steps,seed,preserve_audio,state,attempts,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (jid,actor['user_id'],body.source_video_id,body.reference_image_id,body.client_request_id,
           fingerprint,body.prompt.strip(),body.detect_prompt.strip(),body.quality,body.steps,body.seed,
           int(body.preserve_audio),'queued',0,created,created))
    return {'id':jid,'state':'queued','created_at':created}


@router.get('/jobs')
def list_jobs(actor=Depends(_user)):
    with db.connect() as c:
        _mark_expired(c)
        rows=c.execute('SELECT * FROM cr_jobs WHERE owner_id=? ORDER BY created_at DESC LIMIT 50',
                       (actor['user_id'],)).fetchall()
    return {'items': [_public(dict(row)) for row in rows]}


@router.get('/jobs/{job_id}')
def job(job_id:str,actor=Depends(_user)):
    with db.connect() as c:
        _mark_expired(c)
        return _public(_job(c,actor,job_id))


@router.post('/jobs/{job_id}/cancel')
def cancel(job_id: str, actor=Depends(_mutation)):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE'); row=_job(c,actor,job_id)
        if row['state']=='queued':
            c.execute('UPDATE cr_jobs SET state=?,finished_at=?,updated_at=? WHERE id=?',
                      ('cancelled',now(),now(),job_id))
            return {'state':'cancelled'}
        if row['state'] in ACTIVE:
            c.execute('UPDATE cr_jobs SET state=?,updated_at=? WHERE id=?',('cancel_requested',now(),job_id))
            return {'state':'cancel_requested'}
        return {'state':row['state']}


@router.post('/jobs/{job_id}/retry')
def retry(job_id: str, actor=Depends(_mutation)):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE'); row=_job(c,actor,job_id)
        if row['state'] != 'failed':
            raise HTTPException(409,'Stalled jobs need operator recovery after confirming the old worker stopped; only failed jobs can retry')
        if row['attempts'] >= MAX_ATTEMPTS:
            raise HTTPException(409,'Retry limit reached')
        c.execute('''UPDATE cr_jobs SET state='queued',lease_hash=NULL,lease_until=NULL,worker_id=NULL,
                     error=NULL,updated_at=? WHERE id=?''',(now(),job_id))
    return {'state':'queued'}


@router.post('/jobs/{job_id}/recover')
def recover_stalled(job_id: str, body: RecoverRequest, actor=Depends(_mutation)):
    """Human operator confirms old GPU process is down before re-queue is permitted.

    An expired lease alone cannot prove the previous generation stopped.
    """
    if not {'admin', 'superadmin'}.intersection(set(actor.get('roles', []))):
        raise HTTPException(403,'Operator access required')
    if body.confirm_worker_stopped is not True:
        raise HTTPException(422,'Explicit worker-stop verification required')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM cr_jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404,'Job not found')
        if row['state'] != 'stalled':
            raise HTTPException(409,'Only stalled jobs can be recovered')
        c.execute("""UPDATE cr_jobs SET state='failed',error=?,finished_at=?,updated_at=? WHERE id=?""",
                  ('Operator verified prior execution stopped; safe to retry',now(),now(),job_id))
    return {'state':'failed', 'can_retry':row['attempts']<MAX_ATTEMPTS}


@router.get('/jobs/{job_id}/result')
def result(job_id:str,actor=Depends(_user)):
    with db.connect() as c: row=_job(c,actor,job_id)
    if row['state']!='succeeded' or not row['output_key']:
        raise HTTPException(404,'Result not available')
    # R2 StreamingBody is closed in the generator even if the client disconnects.
    try: obj=storage.get_object(row['output_key'])
    except Exception as exc: raise HTTPException(503,'Private video unavailable') from exc
    def stream():
        try:
            for chunk in obj['Body'].iter_chunks(chunk_size=1024*1024):
                if chunk:yield chunk
        finally: obj['Body'].close()
    return StreamingResponse(stream(),media_type='video/mp4',headers={
        'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
        'Content-Disposition':f'attachment; filename="scail2-{job_id}.mp4"'})


@router.get('/jobs/{job_id}/preview')
def preview_result(job_id: str, request: Request, actor=Depends(_user)):
    """Private seekable MP4 response; Range requests forward only to the authorized R2 key."""
    with db.connect() as c: row=_job(c,actor,job_id)
    if row['state']!='succeeded' or not row['output_key']:
        raise HTTPException(404,'Preview not available')
    total=int(row['output_size'] or 0)
    if not total:raise HTTPException(404,'Output size unknown')
    range_header=request.headers.get('range','')
    status=200
    first,last=0,total-1
    if range_header:
        m=re.fullmatch(r'bytes=(\d*)-(\d*)',range_header.strip())
        if not m or (not m.group(1) and not m.group(2)):
            raise HTTPException(416,'Unsupported byte range')
        if not m.group(1):
            suffix=int(m.group(2)); first=max(0,total-suffix)
        else:
            first=int(m.group(1))
        if m.group(2) and m.group(1):last=min(total-1,int(m.group(2)))
        if first>=total or first>last:raise HTTPException(416,'Range not satisfiable')
        status=206
    kwargs={'Bucket':settings.r2_bucket,'Key':row['output_key']}
    if status==206:kwargs['Range']=f'bytes={first}-{last}'
    try: obj=storage.client().get_object(**kwargs)
    except Exception as exc:raise HTTPException(503,'Video temporarily unavailable') from exc
    def chunks():
        try:
            for piece in obj['Body'].iter_chunks(chunk_size=1024*1024):
                if piece:yield piece
        finally:obj['Body'].close()
    headers={'Cache-Control':'private, no-store','Accept-Ranges':'bytes',
             'X-Content-Type-Options':'nosniff','Content-Length':str(last-first+1)}
    if status==206:headers['Content-Range']=f'bytes {first}-{last}/{total}'
    return StreamingResponse(chunks(),status_code=status,media_type='video/mp4',headers=headers)


def _worker_job(c, jid, token):
    r=c.execute('SELECT * FROM cr_jobs WHERE id=?',(jid,)).fetchone()
    if not r or not r['lease_hash'] or not hmac.compare_digest(r['lease_hash'],_hash(token)):
        raise HTTPException(409,'Invalid or expired lease')
    if r['lease_until'] is None or r['lease_until'] < time.time():
        raise HTTPException(409,'Lease expired')
    return dict(r)


@router.post('/worker/hello',dependencies=[Depends(_worker)])
def worker_hello(body: WorkerHello):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("""INSERT INTO cr_runtime(id,generation,ready,seen_at)
          VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET
          generation=excluded.generation,ready=excluded.ready,seen_at=excluded.seen_at""",
          (body.generation,int(body.ready),time.time()))
    return {'accepted':True}


@router.post('/worker/claim',dependencies=[Depends(_worker)])
def claim():
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        _mark_expired(c)
        # Never run another GPU job while an expired attempt may still exist.
        if c.execute("SELECT 1 FROM cr_jobs WHERE state='stalled' LIMIT 1").fetchone():
            return {'job':None,'blocked':'operator_recovery_required'}
        if c.execute('SELECT 1 FROM cr_jobs WHERE state IN ("preparing","running","uploading","cancel_requested") LIMIT 1').fetchone():
            return {'job':None}
        r=c.execute("SELECT * FROM cr_jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not r:return {'job':None}
        video=c.execute('SELECT * FROM cr_assets WHERE id=? AND owner_id=? AND kind=?',
                        (r['source_video_id'],r['owner_id'],'video')).fetchone()
        ref=c.execute('SELECT * FROM cr_assets WHERE id=? AND owner_id=? AND kind=?',
                      (r['reference_image_id'],r['owner_id'],'reference')).fetchone()
        if video is None or ref is None:
            raise HTTPException(409,'Job input asset missing')
        next_attempt=r['attempts']+1
        output_key=f'outputs/character-replace/{r["id"]}/attempt-{next_attempt}.mp4'
        # All presigns must succeed BEFORE committing exclusive claim;
        # otherwise a failed signer leaves an orphan preparing lease.
        put=storage.client().generate_presigned_url('put_object',Params={
            'Bucket':settings.r2_bucket,'Key':output_key,'ContentType':'video/mp4'},ExpiresIn=21600)
        source_url=storage.presign_get(video['r2_key'],ttl=3600)
        reference_url=storage.presign_get(ref['r2_key'],ttl=3600)
        token=uuid4().hex+uuid4().hex
        updated=c.execute('''UPDATE cr_jobs SET state='preparing',lease_hash=?,lease_until=?,attempts=attempts+1,
                  worker_id='scail2',updated_at=?,started_at=COALESCE(started_at,?) WHERE id=? AND state='queued' ''',
                  (_hash(token),time.time()+LEASE_SECONDS,now(),now(),r['id']))
        if updated.rowcount!=1:
            raise HTTPException(409,'Job no longer queued')
    return {'job':{'id':r['id'],'lease_token':token,'quality':r['quality'],'steps':r['steps'],
        'prompt':r['prompt'],'detect_prompt':r['detect_prompt'],'seed':r['seed'],
        'preserve_audio':bool(r['preserve_audio']), 'video_fps':video['fps'],
        'source_size_bytes':video['size_bytes'],
        'longform':video['mime']=='application/octet-stream',
        'source_url':source_url,'reference_url':reference_url,
        'source_ext':Path(video['r2_key']).suffix,'reference_ext':Path(ref['r2_key']).suffix,
        'output_key':output_key,'output_put_url':put}}


@router.post('/worker/output-url',dependencies=[Depends(_worker)])
def refresh_output_url(evt:Heartbeat):
    # Long-form renders may outlive the 6-hour presign issued at claim.
    with db.connect() as c:
        row=_worker_job(c,evt.job_id,evt.lease_token)
        if row['state'] not in {'preparing','running','uploading'}:
            raise HTTPException(409,'Job is no longer active')
        key=f'outputs/character-replace/{row["id"]}/attempt-{row["attempts"]}.mp4'
    try:
        url=storage.client().generate_presigned_url('put_object',Params={
            'Bucket':settings.r2_bucket,'Key':key,'ContentType':'video/mp4'},ExpiresIn=21600)
    except Exception as exc:raise HTTPException(503,'Cannot sign output upload') from exc
    return {'url':url}


@router.post('/worker/heartbeat',dependencies=[Depends(_worker)])
def heartbeat(evt:Heartbeat):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE'); r=_worker_job(c,evt.job_id,evt.lease_token)
        if r['state'] not in ACTIVE:
            raise HTTPException(409,'Job already terminal')
        c.execute('UPDATE cr_jobs SET lease_until=?,updated_at=? WHERE id=?',
                  (time.time()+LEASE_SECONDS,now(),r['id']))
    return {'cancel_requested': r['state']=='cancel_requested'}


@router.post('/worker/event',dependencies=[Depends(_worker)])
def event(evt:WorkerEvent):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE'); r=_worker_job(c,evt.job_id,evt.lease_token)
        if r['state']=='cancel_requested' and evt.state not in {'cancelled'}:
            raise HTTPException(409,'Job cancellation requested')
        if evt.state in {'preparing','running','uploading'}:
            if r['state'] not in ACTIVE or (evt.state=='preparing' and r['state']!='preparing') or (evt.state=='running' and r['state'] not in {'preparing','running'}) or (evt.state=='uploading' and r['state'] not in {'running','uploading'}):
                raise HTTPException(409,'Invalid Job state transition')
            c.execute('UPDATE cr_jobs SET state=?,updated_at=? WHERE id=?',(evt.state,now(),r['id']))
        elif evt.state in {'failed','cancelled'}:
            c.execute('''UPDATE cr_jobs SET state=?,error=?,lease_hash=NULL,lease_until=NULL,
                finished_at=?,updated_at=? WHERE id=?''',
                      (evt.state,evt.error[:300] or None,now(),now(),r['id']))
        elif evt.state=='succeeded':
            if r['state'] not in {'uploading','running'}:
                raise HTTPException(409,'Output cannot be completed before execution')
            output_key=f'outputs/character-replace/{r["id"]}/attempt-{r["attempts"]}.mp4'
            try: head=storage.client().head_object(Bucket=settings.r2_bucket,Key=output_key)
            except Exception as exc: raise HTTPException(503,'Output not yet available in R2') from exc
            size=int(head.get('ContentLength',0))
            if size<1024 or head.get('ContentType') not in {'video/mp4','application/octet-stream'}:
                raise HTTPException(422,'Invalid output video')
            c.execute('''UPDATE cr_jobs SET state='succeeded',output_key=?,output_size=?,lease_hash=NULL,
                lease_until=NULL,finished_at=?,updated_at=? WHERE id=?''',
                      (output_key,size,now(),now(),r['id']))
    return {'accepted':True}
