"""Phase06 owner-only media API. Registered BEFORE legacy and Phase03 /assets routes.

No public asset URLs, no service or admin-token authentication, no GPU dispatch.
Every asset is looked up from the active server-side session using SQL owner predicates.
"""
from __future__ import annotations
import base64,hashlib,hmac,io,json,os,re,warnings
from datetime import datetime,timezone
from uuid import uuid4
from fastapi import APIRouter,Depends,File,HTTPException,Request,UploadFile
from fastapi.responses import StreamingResponse,Response
from PIL import Image,ImageOps,UnidentifiedImageError
from . import db,security,storage,media_repository as media
from .config import settings


def ready():
 if os.getenv('MEDIA_LIBRARY_ENABLED','false').lower()!='true' or os.getenv('OWNER_ISOLATION_ENABLED','false').lower()!='true':
  raise HTTPException(503,'Private media library requires verified owner isolation')
 security.policy()
 with db.connect() as c:
  try:media.require_schema(c)
  except (media.NotReady,media.owners.MissingOwnerSchema) as e:raise HTTPException(503,str(e)) from e
router=APIRouter(prefix='/api',tags=['Private media'],dependencies=[Depends(ready)])
user_dep=Depends(security.require_active_user)
NO_STORE={'Cache-Control':'private, no-store, max-age=0','Pragma':'no-cache',
          'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'}
ROLES={'identity','clothing','pose','background','mask','reference','start_frame','end_frame'}


def missing():raise HTTPException(404,'Asset not found')
def mac(data):return hmac.new(os.environ['AUTH_CSRF_SECRET'].encode(),data.encode(),hashlib.sha256).hexdigest()
def cursor_encode(uid,filters,point):
 payload=json.dumps({'uid':uid,'filters':filters,'at':point[0],'id':point[1]},sort_keys=True,separators=(',',':'))
 return base64.urlsafe_b64encode((payload+'.'+mac(payload)).encode()).decode().rstrip('=')
def cursor_decode(raw,uid,filters):
 if not raw:return None
 if len(raw)>2048:raise HTTPException(422,'Invalid cursor')
 try:
  data=base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)).decode()
  body,sig=data.rsplit('.',1)
  if not hmac.compare_digest(mac(body),sig):raise ValueError()
  parsed=json.loads(body)
  if parsed['uid']!=uid or parsed['filters']!=filters:raise ValueError()
  if not all(isinstance(parsed[k],str) and len(parsed[k])<=100 for k in ('at','id')):raise ValueError()
  return parsed['at'],parsed['id']
 except (ValueError,KeyError,TypeError,UnicodeError):raise HTTPException(422,'Invalid cursor')


def safe(a):
 return {k:a.get(k) for k in ('asset_id','mime_type','width','height','size_bytes','created_at','kind','job_id') if k in a}

def source(c,uid,aid):
 a=media.available_asset(c,uid,aid)
 if a is None:missing()
 key=a['storage_key']
 if not isinstance(key,str) or not key or '..' in key.split('/') or '\\' in key:
  missing()
 if a['kind']=='output':
  if not a.get('job_id') or not key.startswith('outputs/'+a['job_id']+'/'):missing()
 elif not key.startswith('inputs/'):missing()
 return a

@router.get('/assets')
def assets(limit:int=24,cursor:str|None=None,type:str|None=None,kind:str|None=None,
           status:str|None=None,model:str|None=None,project:str|None=None,
           after:str|None=None,before:str|None=None,user=user_dep):
 typ=kind or type
 filters={'type':typ,'status':status,'model':model,'project':project,'after':after,'before':before}
 pos=cursor_decode(cursor,user['user_id'],filters)
 try:
  with db.connect() as c:
   rows,next_point=media.asset_page(c,user['user_id'],limit=limit,cursor=pos,kind=typ,
     after=after,before=before,status=status,model=model,project=project)
 except ValueError as e:raise HTTPException(422,str(e)) from e
 return Response(content=json.dumps({'items':[safe(a) for a in rows],
   'next_cursor':cursor_encode(user['user_id'],filters,next_point) if next_point else None}),
   media_type='application/json',headers=NO_STORE)

@router.get('/assets/{asset_id}')
def detail(asset_id:str,user=user_dep):
 with db.connect() as c:
  a=source(c,user['user_id'],asset_id)
  data=safe(a)
  data['variants']=[{'kind':r['kind'],'width':r['width'],'height':r['height']}
   for r in c.execute('SELECT kind,width,height FROM asset_variants WHERE asset_id=? AND owner_user_id=?',
                      (asset_id,user['user_id']))]
  data['references']=media.lineage(c,user['user_id'],asset_id)
 return Response(content=json.dumps(data),media_type='application/json',headers=NO_STORE)

def stream_object(key,media_type,*,disposition=None):
 try:obj=storage.get_object(key)
 except Exception:raise HTTPException(404,'Private media unavailable')
 headers=dict(NO_STORE)
 if disposition:headers['Content-Disposition']=disposition
 if isinstance(obj.get('ContentLength'),int) and obj['ContentLength']>=0:headers['Content-Length']=str(obj['ContentLength'])
 def iterate():
  try:yield from obj['Body'].iter_chunks(chunk_size=256*1024)
  finally:obj['Body'].close()
 return StreamingResponse(iterate(),media_type=media_type or 'application/octet-stream',headers=headers)

@router.get('/assets/{asset_id}/thumbnail')
def thumbnail(asset_id:str,user=user_dep):
 with db.connect() as c:
  source(c,user['user_id'],asset_id)
  v=media.variant(c,user['user_id'],asset_id)
  if v is None:raise HTTPException(404,'Thumbnail is not prepared')
 return stream_object(v['storage_key'],v['mime_type'])

@router.get('/assets/{asset_id}/preview')
def preview(asset_id:str,user=user_dep):
 with db.connect() as c:a=source(c,user['user_id'],asset_id)
 return stream_object(a['storage_key'],a['mime_type'])

@router.get('/assets/{asset_id}/download')
def download(asset_id:str,user=user_dep):
 with db.connect() as c:a=source(c,user['user_id'],asset_id)
 ext={'image/png':'png','image/jpeg':'jpg','image/webp':'webp','image/gif':'gif','video/mp4':'mp4','video/webm':'webm'}.get(a['mime_type'],'bin')
 return stream_object(a['storage_key'],a['mime_type'],disposition=f'attachment; filename="media-{asset_id[:32]}.{ext}"')

@router.post('/assets/{asset_id}/download-ticket')
def ticket(asset_id:str,request:Request,user=user_dep):
 security.require_csrf(request)
 with db.connect() as c:a=source(c,user['user_id'],asset_id)
 # Optional short-lived bearer URL; always subject to initial owner validation.
 ttl=min(60,max(1,settings.r2_presign_ttl_seconds))
 return Response(content=json.dumps({'url':storage.presign_get(a['storage_key'],ttl=ttl),'expires_in':ttl}),
                 media_type='application/json',headers=NO_STORE)

@router.post('/assets/{asset_id}/reuse')
def reuse(asset_id:str,request:Request,role:str='reference',slot:str='input.image_1',user=user_dep):
 security.require_csrf(request)
 if role not in ROLES or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}',slot):raise HTTPException(422,'Invalid role or slot')
 with db.connect() as c:a=source(c,user['user_id'],asset_id)
 # No permanent reference is written before a real Job is atomically created.
 return Response(content=json.dumps({'asset_id':asset_id,'role':role,'slot_key':slot,
   'source_job_id':a.get('job_id'),'state':'draft_only','can_submit':False}),
   media_type='application/json',headers=NO_STORE)

@router.get('/assets/{asset_id}/lineage')
def lineage(asset_id:str,user=user_dep):
 with db.connect() as c:
  refs=media.lineage(c,user['user_id'],asset_id)
  if refs is None:missing()
 return Response(content=json.dumps({'references':refs}),media_type='application/json',headers=NO_STORE)

@router.delete('/assets/{asset_id}',status_code=204)
def soft_delete(asset_id:str,request:Request,user=user_dep):
 security.require_csrf(request)
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  outcome=media.soft_delete(c,user['user_id'],asset_id,datetime.now(timezone.utc).isoformat())
  if outcome=='missing':missing()
  if outcome=='referenced':raise HTTPException(409,'Asset is referenced by a Job; deletion blocked')
 return Response(status_code=204,headers=NO_STORE)

@router.post('/uploads',status_code=201)
def upload(request:Request,file:UploadFile=File(...),user=user_dep):
 security.require_csrf(request)
 cap=min(max(int(settings.max_upload_mb),1),50)*1024*1024
 raw=file.file.read(cap+1)
 if not raw or len(raw)>cap:raise HTTPException(413,'Invalid image size')
 try:
  with warnings.catch_warnings():
   warnings.simplefilter('error',Image.DecompressionBombWarning)
   with Image.open(io.BytesIO(raw)) as img:
    fmt=img.format
    if fmt not in ('PNG','JPEG','WEBP','GIF') or img.width*img.height>40_000_000:raise ValueError()
    img.verify()
   with Image.open(io.BytesIO(raw)) as img:
    img.load();width,height=img.size
    reduced=ImageOps.exif_transpose(img).convert('RGB')
    reduced.thumbnail((512,512),Image.Resampling.LANCZOS)
    thumb=io.BytesIO();reduced.save(thumb,format='WEBP',quality=78,method=4)
 except (ValueError,OSError,UnidentifiedImageError,Image.DecompressionBombWarning,Image.DecompressionBombError):
  raise HTTPException(422,'Unsupported or corrupt image')
 mime={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp','GIF':'image/gif'}[fmt]
 if file.content_type and file.content_type not in (mime,'application/octet-stream'):
  raise HTTPException(422,'Image content-type mismatch')
 aid=str(uuid4());ext={'PNG':'png','JPEG':'jpg','WEBP':'webp','GIF':'gif'}[fmt]
 key=f'inputs/{aid}/original.{ext}';tkey=f'thumbnails/{aid}/512.webp'
 # R2 IO outside SQLite write lock. On failure, unreferenced private blobs need GC review.
 try:
  storage.upload_fileobj(io.BytesIO(raw),key,mime)
  storage.upload_fileobj(io.BytesIO(thumb.getvalue()),tkey,'image/webp')
  # HEAD verification: a successful upload call alone is not evidence of durable storage.
  for name,expected,mtype in ((key,len(raw),mime),(tkey,len(thumb.getvalue()),'image/webp')):
   head=storage.client().head_object(Bucket=settings.r2_bucket,Key=name)
   if int(head.get('ContentLength',-1))!=expected or head.get('ContentType','').split(';')[0]!=mtype:
    raise RuntimeError('R2 returned inconsistent media metadata')
 except Exception:raise HTTPException(503,'Private storage temporarily unavailable')
 instant=datetime.now(timezone.utc).isoformat()
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  c.execute('''INSERT INTO input_assets(asset_id,storage_key,mime_type,size_bytes,width,height,
    created_at,owner_user_id,ownership_state) VALUES(?,?,?,?,?,?,?,?,?)''',
    (aid,key,mime,len(raw),width,height,instant,user['user_id'],'verified'))
  c.execute('''INSERT INTO asset_variants(id,asset_id,owner_user_id,kind,storage_key,mime_type,
    width,height,size_bytes,verified_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
    (str(uuid4()),aid,user['user_id'],'thumbnail',tkey,'image/webp',
     reduced.width,reduced.height,len(thumb.getvalue()),instant,instant))
 return Response(status_code=201,content=json.dumps({'asset_id':aid,'mime_type':mime,'width':width,
   'height':height,'size_bytes':len(raw),'thumbnail_url':f'/api/assets/{aid}/thumbnail'}),
   media_type='application/json',headers=NO_STORE)

@router.post('/jobs/{job_id}/references')
def bind_reference_disabled(job_id:str,request:Request,user=user_dep):
 security.require_csrf(request)
 with db.connect() as c:
  from . import owner_repository as owners
  if owners.job(c,user['user_id'],job_id) is None:raise HTTPException(404,'Job not found')
 raise HTTPException(503,'Atomic Job creation and immutable lineage need Phase03 security gate')
