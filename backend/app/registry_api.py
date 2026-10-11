"""Phase07 opt-in registry. NO provider call, no secret disclosure, no fake runtime verification."""
from __future__ import annotations
import os,re,json,sqlite3
from uuid import uuid4
from fastapi import APIRouter,Depends,Request,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from . import db,security

router=APIRouter(prefix='/api',tags=['Model registry'])
HEX=re.compile(r'^[a-f0-9]{64}$')
GHCR=re.compile(r'^ghcr\.io/[a-z0-9._-]+/[a-z0-9._/-]+$')
VAULT=re.compile(r'^vault://[a-zA-Z0-9/_-]{1,200}$')
NAME=re.compile(r'^[A-Za-z0-9_.-]{1,120}$')
SCHEMA_TABLES={'model_families','model_versions','worker_images','deployment_profiles','registry_audit'}

def gate():
 if os.getenv('MODEL_REGISTRY_ENABLED','false').lower()!='true':raise HTTPException(503,'Registry disabled')
 security.policy()
 with db.connect() as c:
  if not SCHEMA_TABLES<={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
   raise HTTPException(503,'Phase07 migration not applied')

def user(actor=Depends(security.require_active_user),_=Depends(gate)):return actor
def admin(actor=Depends(user)):
 if not {'admin','superadmin'} & set(actor.get('roles',[])):raise HTTPException(403,'Admin required')
 return actor
def write(request:Request,actor=Depends(admin)):
 security.require_csrf(request);return actor

def audit(c,actor,action,target):
 c.execute('INSERT INTO registry_audit VALUES(?,?,?,?,?)',(str(uuid4()),actor['user_id'],action,target,security.iso()))
def encode(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def allrows(c,sql,args=()):return [dict(r) for r in c.execute(sql,args)]
def sha(value):
 if not HEX.fullmatch(value):raise HTTPException(422,'SHA256 digest must be lowercase hexadecimal')
def found(c,table,key):
 if table not in {'model_families','model_versions','worker_images','gpu_profiles','deployment_profiles','deployment_profile_revisions'}:raise RuntimeError('Unknown table')
 if not c.execute('SELECT 1 FROM '+table+' WHERE id=?',(key,)).fetchone():raise HTTPException(404,'Object not found')
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Family(Strict):
 name:str=Field(min_length=1,max_length=120)
 vendor:str=Field(min_length=1,max_length=120)
 modality:str=Field(pattern='^(image|video|multimodal)$')
 description:str=Field(default='',max_length=500)
class Model(Strict):
 family_id:str
 revision:str=Field(min_length=1,max_length=100)
 license_id:str=Field(min_length=2,max_length=120)
 artifact_sha256:str
 precision:str=Field(pattern='^(fp32|fp16|bf16|fp8|int8|int4)$')
 vram_gb:int=Field(ge=1,le=512)
 capabilities:dict=Field(default_factory=dict)
class Artifact(Strict):
 model_id:str
 kind:str=Field(pattern='^(checkpoint|lora|vae|clip|encoder|controlnet)$')
 sha256:str
 size_bytes:int=Field(gt=0,le=2_000_000_000_000)
 logical_name:str
class Image(Strict):
 name:str=Field(min_length=1,max_length=120)
 repo:str
 tag:str
 digest:str
 build_sha:str|None=None
 comfyui_version:str|None=None
 nodes:list[str]=Field(default_factory=list,max_length=1000)
class GPU(Strict):
 name:str=Field(min_length=1,max_length=120)
 gpu_family:str=Field(min_length=1,max_length=120)
 provider:str=Field(pattern='^salad$')
 vram_gb:int=Field(ge=1,le=512)
 ram_gb:int=Field(ge=1,le=1024)
 cpu_count:int=Field(ge=1,le=128)
 disk_gb:int=Field(ge=1,le=2000)
 shm_mb:int=Field(ge=1,le=131072)
class Profile(Strict):name:str=Field(min_length=1,max_length=120)
class Revision(Strict):
 image_id:str
 gpu_id:str
 config:dict
 env:dict=Field(default_factory=dict)
class State(Strict):status:str=Field(pattern='^(testing|deprecated)$')

# A model can be 'ready' in a legacy table without evidence: THAT NEVER makes it visible.
VERIFIED='''EXISTS (SELECT 1 FROM image_model_compatibility ic
 JOIN worker_images wi ON wi.id=ic.image_id
 JOIN deployment_profile_revisions rev ON rev.image_id=wi.id
 JOIN deployment_profiles p ON p.active_revision_id=rev.id
 JOIN model_deployment_compatibility dc ON dc.revision_id=rev.id AND dc.model_id=v.id
 WHERE ic.model_id=v.id AND ic.state='tested_pass' AND wi.signature_status='verified'
 AND wi.status='approved' AND rev.status='active' AND dc.state='tested_pass')'''
@router.get('/catalog/models')
def catalog(modality:str|None=None,actor=Depends(user)):
 if modality not in (None,'image','video','multimodal'):raise HTTPException(422,'Bad modality')
 with db.connect() as c:
  sql='''SELECT v.id,v.revision,f.name,f.vendor,f.modality,f.description,v.precision,v.capabilities_json
    FROM model_versions v JOIN model_families f ON f.id=v.family_id WHERE v.status='ready' AND '''+VERIFIED
  args=[]
  if modality:sql+=' AND f.modality=?';args.append(modality)
  result=allrows(c,sql+' ORDER BY f.name LIMIT 100',args)
  for r in result:r['capabilities']=json.loads(r.pop('capabilities_json'));r['readiness']='unknown';r['cost']='unavailable'
  return {'items':result}
@router.get('/models/{model_id}')
def model_public(model_id:str,actor=Depends(user)):
 with db.connect() as c:
  r=c.execute('''SELECT v.id,v.revision,v.capabilities_json,v.license_id,f.name,f.vendor,f.modality,f.description
  FROM model_versions v JOIN model_families f ON f.id=v.family_id
  WHERE v.id=? AND v.status='ready' AND '''+VERIFIED,(model_id,)).fetchone()
  if r is None:raise HTTPException(404,'Model unavailable')
  data=dict(r);data['capabilities']=json.loads(data.pop('capabilities_json'));data['readiness']='unknown';return data
@router.get('/models/{model_id}/capabilities')
def model_capabilities(model_id:str,actor=Depends(user)):
 m=model_public(model_id,actor);return {'id':m['id'],'capabilities':m['capabilities'],'readiness':'unknown'}

@router.get('/admin/models')
def list_models(actor=Depends(admin)):
 with db.connect() as c:return {'families':allrows(c,'SELECT * FROM model_families ORDER BY created_at DESC LIMIT 100'),
 'versions':allrows(c,'SELECT id,family_id,revision,license_id,artifact_sha256,precision,vram_gb,status FROM model_versions LIMIT 100'),
 'artifacts':allrows(c,'SELECT * FROM model_artifacts LIMIT 100')}
@router.post('/admin/models/families',status_code=201)
def create_family(data:Family,actor=Depends(write)):
 oid=str(uuid4())
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');c.execute('INSERT INTO model_families VALUES(?,?,?,?,?,?)',(oid,data.name,data.vendor,data.modality,data.description,security.iso()));audit(c,actor,'family.create',oid)
 return {'id':oid}
@router.post('/admin/models',status_code=201)
def create_model(data:Model,actor=Depends(write)):
 sha(data.artifact_sha256)
 if not re.fullmatch(r'[A-Za-z0-9 .:+/_-]{2,120}',data.license_id):raise HTTPException(422,'Invalid license')
 if len(encode(data.capabilities))>10000 or any(k in encode(data.capabilities).lower() for k in ('secret','password','token','s3://','vault://')):raise HTTPException(422,'Unsafe capabilities')
 oid=str(uuid4())
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');found(c,'model_families',data.family_id)
  try:c.execute('INSERT INTO model_versions(id,family_id,revision,license_id,artifact_sha256,precision,vram_gb,capabilities_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
  (oid,data.family_id,data.revision,data.license_id,data.artifact_sha256,data.precision,data.vram_gb,encode(data.capabilities),security.iso()))
  except sqlite3.IntegrityError as e:raise HTTPException(409,'Duplicate model version') from e
  audit(c,actor,'model.create',oid)
 return {'id':oid,'status':'draft'}
@router.post('/admin/model-artifacts',status_code=201)
def artifact(data:Artifact,actor=Depends(write)):
 sha(data.sha256)
 if not NAME.fullmatch(data.logical_name):raise HTTPException(422,'Artifact logical name must not be a path')
 oid=str(uuid4())
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');found(c,'model_versions',data.model_id)
  c.execute('INSERT INTO model_artifacts VALUES(?,?,?,?,?,?)',(oid,data.model_id,data.kind,data.sha256,data.size_bytes,data.logical_name))
  audit(c,actor,'artifact.create',oid)
 return {'id':oid}
@router.patch('/admin/models/{model_id}')
def model_state(model_id:str,data:State,actor=Depends(write)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');found(c,'model_versions',model_id)
  result=c.execute('UPDATE model_versions SET status=? WHERE id=? AND status IN (\'draft\',\'testing\',\'deprecated\')',(data.status,model_id))
  if result.rowcount!=1:raise HTTPException(409,'Immutable model state')
  audit(c,actor,'model.status',model_id)
 return {'id':model_id,'status':data.status}

@router.get('/admin/worker-images')
def list_images(actor=Depends(admin)):
 with db.connect() as c:
  result=allrows(c,'SELECT * FROM worker_images ORDER BY created_at DESC LIMIT 100')
  for a in result:a['nodes']=json.loads(a.pop('node_inventory_json'))
  return {'items':result}
@router.post('/admin/worker-images',status_code=201)
def create_image(data:Image,actor=Depends(write)):
 if not GHCR.fullmatch(data.repo) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}',data.tag) or not data.digest.startswith('sha256:'):raise HTTPException(422,'Trusted GHCR digest required')
 trusted={item.strip().lower() for item in os.getenv('MODEL_REGISTRY_TRUSTED_REPOS','').split(',') if item.strip()}
 if not trusted:raise HTTPException(503,'Trusted GHCR allowlist not configured')
 if data.repo.lower() not in trusted:raise HTTPException(403,'Worker repository not allowlisted')
 sha(data.digest[7:])
 if data.build_sha and not re.fullmatch(r'[a-f0-9]{40}',data.build_sha):raise HTTPException(422,'Invalid build SHA')
 if any(not NAME.fullmatch(n) for n in data.nodes):raise HTTPException(422,'Unsafe node name')
 oid=str(uuid4())
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  try:c.execute('INSERT INTO worker_images(id,name,repo,tag,digest,build_sha,node_inventory_json,comfyui_version,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
   (oid,data.name,data.repo,data.tag,data.digest,data.build_sha,encode(data.nodes),data.comfyui_version,security.iso()))
  except sqlite3.IntegrityError as e:raise HTTPException(409,'Digest already registered') from e
  audit(c,actor,'worker_image.create',oid)
 return {'id':oid,'status':'draft','signature_status':'unknown'}
@router.patch('/admin/worker-images/{image_id}')
def image_state(image_id:str,data:State,actor=Depends(write)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');found(c,'worker_images',image_id)
  result=c.execute('UPDATE worker_images SET status=? WHERE id=? AND status IN (\'draft\',\'testing\',\'deprecated\')',(data.status,image_id))
  if result.rowcount!=1:raise HTTPException(409,'Immutable Worker Image state')
  audit(c,actor,'worker_image.status',image_id)
 return {'id':image_id,'status':data.status}
@router.get('/admin/gpu-profiles')
def gpus(actor=Depends(admin)):
 with db.connect() as c:return {'items':allrows(c,'SELECT * FROM gpu_profiles LIMIT 100')}
@router.post('/admin/gpu-profiles',status_code=201)
def create_gpu(data:GPU,actor=Depends(write)):
 oid=str(uuid4())
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');c.execute('INSERT INTO gpu_profiles VALUES(?,?,?,?,?,?,?,?,?)',(oid,data.name,data.gpu_family,data.provider,data.vram_gb,data.ram_gb,data.cpu_count,data.disk_gb,data.shm_mb));audit(c,actor,'gpu.create',oid)
 return {'id':oid}
@router.get('/admin/deployment-profiles')
def profiles(actor=Depends(admin)):
 with db.connect() as c:return {'items':allrows(c,'SELECT * FROM deployment_profiles ORDER BY created_at DESC LIMIT 100')}
@router.post('/admin/deployment-profiles',status_code=201)
def create_profile(data:Profile,actor=Depends(write)):
 oid=str(uuid4())
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  try:c.execute('INSERT INTO deployment_profiles VALUES(?,?,?,?)',(oid,data.name,None,security.iso()))
  except sqlite3.IntegrityError as e:raise HTTPException(409,'Duplicate profile') from e
  audit(c,actor,'profile.create',oid)
 return {'id':oid}
@router.get('/admin/deployment-variable-schema')
def env_schema(actor=Depends(admin)):
 with db.connect() as c:return {'items':allrows(c,'SELECT * FROM deployment_variable_schema ORDER BY key')}
CONFIG_KEYS={'min_replicas','max_replicas','idle_timeout_seconds','startup_timeout_seconds','readiness_path','health_path'}
def validate_config(obj):
 if set(obj)!=CONFIG_KEYS:raise HTTPException(422,'Missing or extra profile config')
 for k in ('min_replicas','max_replicas','idle_timeout_seconds','startup_timeout_seconds'):
  if type(obj[k]) is not int or obj[k]<0:raise HTTPException(422,'Invalid numeric config')
 if not 0<=obj['min_replicas']<=obj['max_replicas']<=10:raise HTTPException(422,'Invalid replica range')
 if not 30<=obj['startup_timeout_seconds']<=1800 or not 30<=obj['idle_timeout_seconds']<=86400:raise HTTPException(422,'Invalid timeout')
 for k in ('readiness_path','health_path'):
  if not isinstance(obj[k],str) or not re.fullmatch(r'/[A-Za-z0-9/_-]{1,100}',obj[k]):raise HTTPException(422,'Invalid probe path')
def validate_env(c,obj):
 if len(obj)>30:raise HTTPException(422,'Too many ENV entries')
 for key,value in obj.items():
  r=c.execute('SELECT * FROM deployment_variable_schema WHERE key=?',(key,)).fetchone()
  if r is None:raise HTTPException(422,'Unknown env key')
  if r['secret']:
   if not isinstance(value,str) or not VAULT.fullmatch(value):raise HTTPException(422,'Vault reference required')
  elif r['value_type']=='integer':
   if type(value) is not int or (r['min_value'] is not None and value<r['min_value']) or (r['max_value'] is not None and value>r['max_value']):raise HTTPException(422,'Invalid integer ENV')
  elif r['value_type']=='enum':
   if value not in json.loads(r['enum_json']):raise HTTPException(422,'Invalid enum ENV')
  else:raise HTTPException(422,'Unsupported ENV schema')
@router.post('/admin/deployment-profiles/{profile_id}/revisions',status_code=201)
def create_revision(profile_id:str,data:Revision,actor=Depends(write)):
 validate_config(data.config);oid=str(uuid4())
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');found(c,'deployment_profiles',profile_id);found(c,'worker_images',data.image_id);found(c,'gpu_profiles',data.gpu_id)
  validate_env(c,data.env)
  version=c.execute('SELECT COALESCE(MAX(version),0)+1 FROM deployment_profile_revisions WHERE profile_id=?',(profile_id,)).fetchone()[0]
  c.execute('INSERT INTO deployment_profile_revisions(id,profile_id,version,image_id,gpu_id,config_json,env_json,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
   (oid,profile_id,version,data.image_id,data.gpu_id,encode(data.config),encode(data.env),actor['user_id'],security.iso()))
  audit(c,actor,'revision.create',oid)
 return {'id':oid,'version':version,'status':'draft'}
@router.get('/admin/deployment-profiles/{profile_id}/history')
def revisions(profile_id:str,actor=Depends(admin)):
 with db.connect() as c:
  found(c,'deployment_profiles',profile_id)
  result=allrows(c,'SELECT * FROM deployment_profile_revisions WHERE profile_id=? ORDER BY version DESC LIMIT 100',(profile_id,))
  for r in result:
   r['config']=json.loads(r.pop('config_json'));env=json.loads(r.pop('env_json'))
   r['env']={k:('[configured]' if c.execute('SELECT secret FROM deployment_variable_schema WHERE key=?',(k,)).fetchone()[0] else v) for k,v in env.items()}
  return {'items':result}
@router.post('/admin/deployment-profiles/{profile_id}/validate')
def validate_revision(profile_id:str,revision_id:str,actor=Depends(write)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  r=c.execute('SELECT * FROM deployment_profile_revisions WHERE id=? AND profile_id=?',(revision_id,profile_id)).fetchone()
  if r is None:raise HTTPException(404,'Revision not found')
  validate_config(json.loads(r['config_json']));validate_env(c,json.loads(r['env_json']))
  c.execute("UPDATE deployment_profile_revisions SET status='validated' WHERE id=? AND status='draft'",(revision_id,))
  audit(c,actor,'revision.static_validate',revision_id)
 return {'static_validation':'passed','runtime_validation':'unknown','safe_to_activate':False}
@router.get('/admin/compatibility')
def compatibility(actor=Depends(admin)):
 with db.connect() as c:return {'items':allrows(c,'SELECT * FROM image_model_compatibility LIMIT 100'),'note':'Unknown until trusted runtime verification'}
@router.post('/admin/deployment-profiles/{profile_id}/approve')
def approve(profile_id:str,revision_id:str,actor=Depends(write)):
 raise HTTPException(503,'Trusted signature and Worker test attestations unavailable')
@router.post('/admin/deployment-profiles/{profile_id}/activate')
def activate(profile_id:str,revision_id:str,actor=Depends(write)):
 raise HTTPException(503,'Real provider staging, drain, readiness, and rollback integration unavailable')
@router.post('/admin/deployment-profiles/{profile_id}/rollback')
def rollback(profile_id:str,revision_id:str,actor=Depends(write)):
 raise HTTPException(503,'Provider-fenced rollback unavailable')
@router.get('/admin/registry-audit')
def audit_list(actor=Depends(admin)):
 with db.connect() as c:return {'items':allrows(c,'SELECT * FROM registry_audit ORDER BY at DESC LIMIT 100')}
