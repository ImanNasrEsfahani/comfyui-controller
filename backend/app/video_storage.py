"""Phase13 service-side R2 verifier (NOT wired to legacy finish() callback).

Streams remote bytes into a bounded temporary file, verifies HEAD/GET size and
real ffprobe metadata before any caller may record an available asset. Caller
must authenticate the Worker attempt/lease and verify job ownership separately.
"""
from __future__ import annotations
import hashlib,os,tempfile
from pathlib import Path
from .video_pipeline import probe,verify_decodable,VideoError,MAX_BYTES

CHUNK=1024*1024

def verify_uploaded_video(s3,bucket,key,*,job_id,attempt_id,temp_root=None):
    if (not isinstance(job_id,str) or not isinstance(attempt_id,str) or not job_id or not attempt_id or
        '/' in job_id or '/' in attempt_id or '..' in job_id or '..' in attempt_id):
        raise VideoError('INVALID_ATTEMPT_ID')
    prefix=f'outputs/{job_id}/{attempt_id}/'
    if not isinstance(key,str) or not key.startswith(prefix) or '..' in key.split('/') or '\\' in key:
        raise VideoError('INVALID_R2_OUTPUT_PREFIX')
    head=s3.head_object(Bucket=bucket,Key=key)
    expected=head.get('ContentLength')
    if not isinstance(expected,int) or not 32<expected<=MAX_BYTES:raise VideoError('VIDEO_SIZE_INVALID')
    obj=s3.get_object(Bucket=bucket,Key=key)
    body=obj['Body'];total=0;digest=hashlib.sha256()
    with tempfile.TemporaryDirectory(prefix='video13-',dir=temp_root) as directory:
        path=Path(directory)/('original.webm' if key.endswith('.webm') else 'original.mp4')
        try:
            with path.open('wb') as f:
                while True:
                    chunk=body.read(CHUNK)
                    if not chunk:break
                    total+=len(chunk)
                    if total>MAX_BYTES or total>expected:raise VideoError('VIDEO_SIZE_INVALID')
                    digest.update(chunk);f.write(chunk)
            if total!=expected:raise VideoError('VIDEO_R2_LENGTH_MISMATCH')
            info=probe(path)
            verify_decodable(path,info['duration_seconds'])
            if info['container']=='mp4' and not key.lower().endswith('.mp4'):
                raise VideoError('VIDEO_MIME_MISMATCH')
            if info['container']=='webm' and not key.lower().endswith('.webm'):
                raise VideoError('VIDEO_MIME_MISMATCH')
            claimed=head.get('ContentType')
            if claimed not in (None,'application/octet-stream',info['mime_type']):
                raise VideoError('VIDEO_MIME_MISMATCH')
            return {**info,'sha256':digest.hexdigest(),'verified':True}
        finally:
            if hasattr(body,'close'):body.close()
