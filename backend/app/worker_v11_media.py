"""Strict, independent R2 output verification; no HEAD-only 'success'.

All objects must belong to the exact immutable attempt prefix. The caller
records verified objects only after a fenced lease check, in one transaction.
This module has no direct DB writes, queue transitions or browser endpoints.
"""
from __future__ import annotations
import hashlib
import io
import re
from PIL import Image,ImageFile,UnidentifiedImageError

class MediaViolation(ValueError):pass

Image.MAX_IMAGE_PIXELS=80_000_000
ImageFile.LOAD_TRUNCATED_IMAGES=False
EXTS={'png':('image/png',b'\x89PNG\r\n\x1a\n'),
      'jpg':('image/jpeg',b'\xff\xd8\xff'),
      'webp':('image/webp',b'RIFF')}


def verify_media_bytes(data,ext,*,claimed_mime=None,video_probe=None):
    if not isinstance(data,bytes) or not data or len(data)>250*1024**2:
        raise MediaViolation('invalid_media_size')
    ext=ext.lower().lstrip('.')
    if ext in EXTS:
        mime,magic=EXTS[ext]
        if not data.startswith(magic):raise MediaViolation('invalid_media_magic')
        if ext=='webp' and data[8:12]!=b'WEBP':raise MediaViolation('invalid_media_magic')
        if claimed_mime and claimed_mime not in (mime,'application/octet-stream'):
            raise MediaViolation('mime_mismatch')
        try:
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
            with Image.open(io.BytesIO(data)) as im:
                im.load(); width,height=im.size
                if width<=0 or height<=0 or width*height>80_000_000:
                    raise MediaViolation('dimensions_invalid')
                if (ext=='png' and im.format!='PNG') or (ext=='jpg' and im.format!='JPEG') or (ext=='webp' and im.format!='WEBP'):
                    raise MediaViolation('format_mismatch')
        except (OSError,UnidentifiedImageError,Image.DecompressionBombError) as e:
            raise MediaViolation('media_decode_failed') from e
        return {'mime_type':mime,'size_bytes':len(data),'width':width,'height':height,'sha256':hashlib.sha256(data).hexdigest()}
    if ext in ('mp4','webm'):
        if ext=='mp4':
            if len(data)<32 or data[4:8]!=b'ftyp':raise MediaViolation('invalid_video_magic')
        elif len(data)<32 or not data.startswith(b'\x1a\x45\xdf\xa3'):
            raise MediaViolation('invalid_video_magic')
        if video_probe is None:raise MediaViolation('video_probe_required')
        meta=video_probe(data,ext)
        if not isinstance(meta,dict) or meta.get('duration_seconds',0)<=0 or meta.get('width',0)<=0 or meta.get('height',0)<=0:
            raise MediaViolation('video_probe_failed')
        return dict(mime_type='video/mp4' if ext=='mp4' else 'video/webm',size_bytes=len(data),
                    width=meta['width'],height=meta['height'],duration_seconds=meta['duration_seconds'],
                    sha256=hashlib.sha256(data).hexdigest())
    raise MediaViolation('unsupported_media')


def verify_output_objects(s3,bucket,*,job_id,attempt_id,keys,limit=16,video_probe=None):
    if any(not isinstance(x,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}',x) for x in (job_id,attempt_id)):
        raise MediaViolation('invalid_job_or_attempt')
    if not isinstance(keys,(tuple,list)) or not 1<=len(keys)<=limit or len(set(keys))!=len(keys):
        raise MediaViolation('invalid_output_list')
    prefix=f'outputs/{job_id}/{attempt_id}/'
    results=[]
    for key in keys:
        if not isinstance(key,str) or not key.startswith(prefix) or any(x in {'.','..',''} for x in key.split('/')):
            raise MediaViolation('wrong_output_prefix')
        suffix=key.rsplit('.',1)[-1].lower()
        result={'key':key,'status':'unavailable','error_code':None}
        try:
            head=s3.head_object(Bucket=bucket,Key=key)
            size=head.get('ContentLength',0)
            if not isinstance(size,int) or size<=0 or size>250*1024**2:
                raise MediaViolation('invalid_media_size')
            source=s3.get_object(Bucket=bucket,Key=key)['Body']
            # Read strictly bounded; streaming 250 MiB max for this safe prototype.
            raw=source.read(size+1)
            if len(raw)!=size:raise MediaViolation('object_size_mismatch')
            data=verify_media_bytes(raw,suffix,claimed_mime=head.get('ContentType'),video_probe=video_probe)
            result.update(status='available',**data)
        except MediaViolation as e:
            result['error_code']=str(e)
        results.append(result)
    return results
