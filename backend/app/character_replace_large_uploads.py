"""Owner-scoped, resumable-part R2 uploads for long-form SCAIL-2 source videos.

Only R2 receives file bytes; Controller signs part URLs and verifies a complete
object against declared size. All video decoding and container validation happen
in a sandboxed worker with FFmpeg before submitting any GPU prompt.
"""
from __future__ import annotations

import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import db, storage
from .character_replace_api import _mutation
from .config import settings

router = APIRouter(prefix='/api/v2/character-replace/uploads', tags=['SCAIL-2 large uploads'])
MIB = 1024 * 1024
GIB = 1024 * MIB
MAX_PARTS = 10_000
TTL_SECONDS = 7 * 24 * 3600
# Filename extensions are hints, never treated as proof of video type.
VIDEO_EXTENSIONS = {'.mp4','.m4v','.mov','.mkv','.webm','.avi','.wmv','.flv','.mpg',
                    '.mpeg','.ts','.mts','.m2ts','.3gp','.ogv','.vob','.mxf','.asf'}


def upload_limit():
    try:
        gb = int(os.getenv('CHARACTER_REPLACE_MAX_VIDEO_GIB','20'))
    except ValueError:
        raise RuntimeError('CHARACTER_REPLACE_MAX_VIDEO_GIB must be an integer') from None
    if not 1 <= gb <= 4096:
        raise RuntimeError('CHARACTER_REPLACE_MAX_VIDEO_GIB must be 1..4096')
    return gb * GIB


def _now():
    return datetime.now(timezone.utc).isoformat()


def _session(actor, session_id, active=True):
    with db.connect() as c:
        row = c.execute('SELECT * FROM cr_upload_sessions WHERE id=? AND owner_id=?',
                        (session_id, actor['user_id'])).fetchone()
    if row is None: raise HTTPException(404, 'Upload session not found')
    row = dict(row)
    if active and (row['status'] != 'uploading' or row['expires_at'] <= time.time()):
        raise HTTPException(409, 'Upload session expired or completed')
    return row


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid')
    filename: str = Field(min_length=1,max_length=255)
    size_bytes: int = Field(ge=64)


class Part(BaseModel):
    model_config = ConfigDict(extra='forbid')
    number: int = Field(ge=1,le=MAX_PARTS)


class CompletedPart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    number: int = Field(ge=1,le=MAX_PARTS)
    etag: str = Field(min_length=1,max_length=200)


class Complete(BaseModel):
    model_config = ConfigDict(extra='forbid')
    parts: list[CompletedPart] = Field(min_length=1,max_length=MAX_PARTS)


@router.post('/start',status_code=201)
def start(body: Start, actor=Depends(_mutation)):
    if body.size_bytes > upload_limit():
        raise HTTPException(413, 'File exceeds the configured per-upload storage budget')
    with db.connect() as c:
        n = c.execute("SELECT COUNT(*) FROM cr_upload_sessions WHERE owner_id=? AND status='uploading' AND expires_at>?",
                      (actor['user_id'],time.time())).fetchone()[0]
        if n >= 3: raise HTTPException(429, 'Too many active uploads')
    # 16 MiB minimum and at most 10,000 parts for multipart R2 API.
    part_size = max(16 * MIB,math.ceil(body.size_bytes / MAX_PARTS / MIB)*MIB)
    part_count = math.ceil(body.size_bytes/part_size)
    extension = Path(body.filename).suffix.lower()
    if extension not in VIDEO_EXTENSIONS: extension = '.bin'
    asset_id = str(uuid4())
    session_id = str(uuid4())
    key = f'inputs/character-replace/{actor["user_id"]}/{asset_id}{extension}'
    try:
        remote = storage.client().create_multipart_upload(Bucket=settings.r2_bucket,Key=key,
                                                           ContentType='application/octet-stream')
        remote_upload_id = remote['UploadId']
    except Exception as exc:
        raise HTTPException(503, 'Could not initialize private R2 upload') from exc
    try:
        with db.connect() as c:
            c.execute('''INSERT INTO cr_upload_sessions(id,owner_id,asset_id,r2_key,upload_id,size_bytes,part_size,
                     part_count,status,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                     (session_id,actor['user_id'],asset_id,key,remote_upload_id,body.size_bytes,part_size,
                      part_count,'uploading',time.time()+TTL_SECONDS,_now()))
    except Exception:
        try:storage.client().abort_multipart_upload(Bucket=settings.r2_bucket,Key=key,UploadId=remote_upload_id)
        except Exception:pass
        raise
    return {'session_id':session_id,'part_size':part_size,'part_count':part_count,
            'size_bytes':body.size_bytes,'max_size_bytes':upload_limit()}


@router.post('/{session_id}/part-url')
def part_url(session_id: str, body: Part, actor=Depends(_mutation)):
    row = _session(actor,session_id)
    if body.number > row['part_count']:raise HTTPException(422,'Invalid part number')
    try:
        url = storage.client().generate_presigned_url('upload_part',Params={
            'Bucket':settings.r2_bucket,'Key':row['r2_key'],'UploadId':row['upload_id'],
            'PartNumber':body.number},ExpiresIn=3600)
    except Exception as exc:
        raise HTTPException(503, 'Could not sign upload part') from exc
    return {'url':url,'number':body.number}


@router.post('/{session_id}/complete')
def complete(session_id: str, body: Complete, actor=Depends(_mutation)):
    row = _session(actor,session_id,active=False)
    if row['status']=='completed':
        with db.connect() as c:
            asset=c.execute('SELECT * FROM cr_assets WHERE id=? AND owner_id=?',
                            (row['asset_id'],actor['user_id'])).fetchone()
        if asset:
            return {'asset_id':row['asset_id'],'kind':'video','size_bytes':row['size_bytes'],
                    'width':None,'height':None,'duration':None,'fps':None}
    if row['status']!='uploading' or row['expires_at']<=time.time():
        raise HTTPException(409,'Upload session expired or aborted')
    if len(body.parts)!=row['part_count'] or [p.number for p in body.parts]!=list(range(1,row['part_count']+1)):
        raise HTTPException(422, 'Every uploaded part must be supplied in ascending order')
    if any(not re.fullmatch(r'"?[a-fA-F0-9]{32}"?',p.etag) for p in body.parts):
        raise HTTPException(422, 'Invalid R2 part ETag')
    try:
        storage.client().complete_multipart_upload(Bucket=settings.r2_bucket,Key=row['r2_key'],
            UploadId=row['upload_id'],MultipartUpload={'Parts':[
               {'PartNumber':p.number,'ETag':p.etag} for p in body.parts]})
        head=storage.client().head_object(Bucket=settings.r2_bucket,Key=row['r2_key'])
        if int(head.get('ContentLength',-1))!=row['size_bytes']:
            storage.client().delete_object(Bucket=settings.r2_bucket,Key=row['r2_key'])
            raise HTTPException(422,'Uploaded file size differs from declared size')
    except HTTPException:raise
    except Exception as exc:
        raise HTTPException(503,'R2 failed to finalize the upload') from exc
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('''INSERT OR IGNORE INTO cr_assets(id,owner_id,kind,r2_key,mime,size_bytes,width,height,duration,fps,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(row['asset_id'],actor['user_id'],'video',row['r2_key'],
                'application/octet-stream',row['size_bytes'],0,0,None,None,_now()))
        c.execute("UPDATE cr_upload_sessions SET status='completed' WHERE id=? AND owner_id=?",
                  (session_id,actor['user_id']))
    return {'asset_id':row['asset_id'],'kind':'video','size_bytes':row['size_bytes'],
            'width':None,'height':None,'duration':None,'fps':None}


@router.post('/{session_id}/abort')
def abort(session_id: str, actor=Depends(_mutation)):
    row = _session(actor,session_id,active=False)
    if row['status'] == 'uploading':
        try:storage.client().abort_multipart_upload(Bucket=settings.r2_bucket,Key=row['r2_key'],UploadId=row['upload_id'])
        except Exception as exc:raise HTTPException(503,'R2 could not abort the upload') from exc
        with db.connect() as c:
            c.execute("UPDATE cr_upload_sessions SET status='aborted' WHERE id=? AND owner_id=?",
                      (session_id,actor['user_id']))
    return {'status':'aborted' if row['status']=='uploading' else row['status']}
