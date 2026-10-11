"""Owner-only Phase13 video contract and media read adapters.

Generation intentionally returns 503 until verified runtime/job allocation exists.
No public storage URLs; all reads SQL owner-scoped and browser cookie authenticated.
"""
from __future__ import annotations
import json,os
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field
from . import db,security,media_api,media_repository as media
from .video_pipeline import validate_parameters,VideoError

router=APIRouter(prefix='/api/v2/video',tags=['Private video preview'])
SAFE_HEADERS={'Cache-Control':'private, no-store, max-age=0','X-Content-Type-Options':'nosniff',
              'Referrer-Policy':'no-referrer'}

def gate():
 if os.getenv('VIDEO_V13_ENABLED','false').lower()!='true':raise HTTPException(503,'Video preview is disabled')
 media_api.ready()
 with db.connect() as c:
  if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='video_media_details'").fetchone():
   raise HTTPException(503,'Phase13 migration is required')

user=Depends(security.require_active_user)
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class VideoIntent(Strict):
 model_version_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,96}$')
 intent:str
 prompt:str=Field(min_length=1,max_length=2000)
 seconds:int=Field(ge=1,le=30)
 fps:int=Field(ge=1,le=60)
 width:int=Field(ge=64,le=4096)
 height:int=Field(ge=64,le=4096)
 seed:str=Field(pattern=r'^(0|[1-9][0-9]{0,19})$')
 codec:str
 start_frame:str|None=None
 end_frame:str|None=None

# This SQL is intentionally stricter than a model claiming itself ready.
# Operator must supply a separately authorized, measured video policy via
# verified video policy metadata. No such policy is seeded by migrations.
VERIFIED='''SELECT v.capabilities_json FROM model_versions v
 JOIN model_families f ON f.id=v.family_id
 WHERE v.id=? AND v.status='ready' AND f.modality IN ('video','multimodal')
 AND EXISTS(SELECT 1 FROM model_deployment_compatibility dc
 JOIN deployment_profile_revisions rev ON rev.id=dc.revision_id
 JOIN deployment_profiles dp ON dp.active_revision_id=rev.id
 JOIN worker_images wi ON wi.id=rev.image_id
 JOIN image_model_compatibility ic ON ic.image_id=wi.id AND ic.model_id=v.id
 WHERE dc.model_id=v.id AND dc.state='tested_pass' AND ic.state='tested_pass'
 AND wi.signature_status='verified' AND wi.status='approved' AND rev.status='active')'''

def policy(c,mid):
 row=c.execute(VERIFIED,(mid,)).fetchone()
 if not row:raise HTTPException(503,'No approved video model/profile is available')
 try:
  cap=json.loads(row[0]);video=cap.get('video',{}) if isinstance(cap,dict) else {}
 except (ValueError,TypeError):video={}
 if not isinstance(video,dict):video={}
 if not video.get('runtime_tested') or not isinstance(video.get('evidence_ref'),str) or not video['evidence_ref']:
  raise HTTPException(503,'Real video model runtime evidence is absent')
 if not all(isinstance(video.get(k),list) and video[k] for k in ('intents','dimensions','fps','codecs')) or not isinstance(video.get('max_seconds'),int):
  raise HTTPException(503,'Video parameter policy is incomplete')
 return video

@router.get('/models',dependencies=[Depends(gate)])
def models(actor=user):
 # Never advertise static registration as runtime READY; no sensitive infrastructure inventory.
 with db.connect() as c:
  rows=c.execute('''SELECT v.id,f.name,v.revision FROM model_versions v JOIN model_families f ON f.id=v.family_id
   WHERE f.modality IN ('video','multimodal') AND v.status='ready' ORDER BY f.name,v.revision LIMIT 100''').fetchall()
  items=[]
  for item in rows:
   try:policy(c,item['id'])
   except HTTPException:continue
   items.append({'id':item['id'],'name':item['name'],'revision':item['revision'],
                 'readiness':'unverified_worker','generate_enabled':False})
 return {'items':items,'gpu_execution_enabled':False}

@router.get('/models/{model_id}/parameters',dependencies=[Depends(gate)])
def parameters(model_id:str,actor=user):
 with db.connect() as c:video=policy(c,model_id)
 return {'model_version_id':model_id,'intents':video['intents'],
         'dimensions':video['dimensions'],'fps':video['fps'],'max_seconds':video['max_seconds'],
         'codecs':video['codecs'],'optional_slots':video.get('optional_slots',[]),
         'execution_enabled':False,'runtime_evidence':'operator_registration_not_worker_e2e'}

@router.post('/validate',dependencies=[Depends(gate)])
def validate(body:VideoIntent,request:Request,actor=user):
 security.require_csrf(request)
 uid=actor['user_id'];data=body.model_dump(exclude_none=True)
 with db.connect() as c:
  configured=policy(c,body.model_version_id)
  def owned(aid,kind):
   result=media.available_asset(c,uid,aid)
   return result is not None and result.get('mime_type','').startswith(kind+'/')
  try:effective=validate_parameters(configured,{k:v for k,v in data.items() if k!='model_version_id'},authorize=owned)
  except VideoError as exc:raise HTTPException(422,exc.code) from exc
 return {'valid':True,'effective':{k:v for k,v in effective.items() if k!='prompt'},
         'dispatch_allowed':False,'job_created':False,
         'warning':'Validation does not prove actual ComfyUI execution'}

@router.post('/jobs',dependencies=[Depends(gate)])
def submit_disabled(actor=user):
 raise HTTPException(503,'Video Job acceptance blocked until Phase11/12 runtime E2E is verified')


def video_source(c,uid,aid):
 src=media_api.source(c,uid,aid)
 if src.get('mime_type') not in {'video/mp4','video/webm'}:raise HTTPException(404,'Video not found')
 return src

@router.get('/assets/{asset_id}/original',dependencies=[Depends(gate)])
def original(asset_id:str,actor=user):
 with db.connect() as c:src=video_source(c,actor['user_id'],asset_id)
 extension='webm' if src['mime_type']=='video/webm' else 'mp4'
 return media_api.stream_object(src['storage_key'],src['mime_type'],
          disposition=f'attachment; filename="video-{asset_id[:32]}.{extension}"')

@router.get('/assets/{asset_id}/{variant}',dependencies=[Depends(gate)])
def video_variant(asset_id:str,variant:str,actor=user):
 if variant not in {'poster','proxy'}:raise HTTPException(404,'Variant not found')
 kind='poster' if variant=='poster' else 'preview_proxy'
 with db.connect() as c:
  original_asset=video_source(c,actor['user_id'],asset_id)
  row=c.execute('''SELECT v.storage_key,v.mime_type FROM asset_variants v
   JOIN video_transcode_tasks t ON t.asset_id=v.asset_id AND t.owner_user_id=v.owner_user_id
   AND t.kind=v.kind AND t.status='ready' AND t.verified_storage_key=v.storage_key
   WHERE v.asset_id=? AND v.owner_user_id=? AND v.kind=?''',(asset_id,actor['user_id'],kind)).fetchone()
  if not row:raise HTTPException(404,'Variant unavailable; original may still be downloaded')
  key,mime=row['storage_key'],row['mime_type']
  base=original_asset['storage_key'].rsplit('/',1)[0]+'/'
  if (not key.startswith(base) or key==original_asset['storage_key'] or
      '..' in key.split('/') or '\\' in key):
   raise HTTPException(404,'Variant key invalid')
  if kind=='poster' and mime not in {'image/jpeg','image/png'}:raise HTTPException(404,'Invalid poster type')
  if kind=='preview_proxy' and mime!='video/mp4':raise HTTPException(404,'Invalid proxy type')
 return media_api.stream_object(key,mime)

@router.post('/assets/{asset_id}/reuse',dependencies=[Depends(gate)])
def reuse(asset_id:str,slot:str,request:Request,actor=user):
 security.require_csrf(request)
 if slot!='source_video':raise HTTPException(422,'Video reuse requires an approved video input slot')
 with db.connect() as c:video_source(c,actor['user_id'],asset_id)
 # The editor cannot submit until approved video-edit model/graph exists.
 return {'asset_id':asset_id,'slot_key':slot,'draft_only':True,'job_created':False}
