"""Phase08 isolated safe catalog+parameter intent+private preset APIs.

NEVER queues a Job. No user may inject filesystem paths or remote LoRA URLs.
"""
from __future__ import annotations
import os,re,json,sqlite3
from uuid import uuid4
from fastapi import APIRouter,Depends,Request,Response,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from . import db,security,registry_api
from .dynamic_params import (ParameterError,canonical,checksum,validate_schema,validate_value,
  seed_number,forbid,resolve,compile_lora_graph,render_resolved_graph)

def private_response(response:Response):
 response.headers['Cache-Control']='private, no-store'

router=APIRouter(prefix='/api',tags=['Dynamic parameters and private presets'],dependencies=[Depends(private_response)])
NAME=re.compile(r'^[A-Za-z0-9_.-]{1,120}$');HEX=re.compile(r'^[a-f0-9]{64}$')
SCHEMA_TABLES={'model_parameter_schemas','lora_versions','model_lora_compatibility','lora_installations','user_parameter_presets','parameter_intents'}

def gate():
 if os.getenv('DYNAMIC_PARAMETERS_ENABLED','false').lower()!='true':raise HTTPException(503,'Phase08 disabled')
 registry_api.gate()
 with db.connect() as c:
  tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if not SCHEMA_TABLES<=tables:raise HTTPException(503,'Phase08 migration is required')

def user(actor=Depends(security.require_active_user),_=Depends(gate)):return actor
def mutation(request:Request,actor=Depends(user)):
 security.require_csrf(request);return actor
def admin(actor=Depends(user)):
 if not {'admin','superadmin'}&set(actor['roles']):raise HTTPException(403,'Admin required')
 return actor
def admin_mutation(request:Request,actor=Depends(admin)):
 security.require_csrf(request);return actor

def client_error(err:ParameterError):
 raise HTTPException(422,{'code':err.code,'field_path':err.path,'message':str(err)}) from err

def graph(c,workflow_id):
 row=c.execute('SELECT api_prompt FROM workflows WHERE id=?',(workflow_id,)).fetchone()
 if not row:raise HTTPException(404,'Workflow not found')
 try:
  result=json.loads(row['api_prompt']);
  if not isinstance(result,dict):raise ValueError()
  return result
 except (TypeError,ValueError):raise HTTPException(409,'Saved workflow API graph invalid')

def graph_hash(g):return checksum(g)

def public_model(c,mid):
 q='''SELECT v.id,v.family_id,v.revision FROM model_versions v WHERE v.id=? AND v.status='ready' AND '''+registry_api.VERIFIED
 row=c.execute(q,(mid,)).fetchone()
 if not row:raise HTTPException(404,'Model is not published and runtime-compatible')
 return dict(row)

def schema_by(c,model_id,workflow_id,schema_hash=None,*,public=True):
 where="status='published'" if public else '1=1'
 query='''SELECT * FROM model_parameter_schemas WHERE model_id=? AND workflow_id=? AND '''+where
 args=[model_id,workflow_id]
 if schema_hash:query+=' AND schema_hash=?';args.append(schema_hash)
 query+=' ORDER BY created_at DESC,id DESC LIMIT 1'
 row=c.execute(query,args).fetchone()
 if not row:raise HTTPException(404,'Compatible parameter schema unavailable')
 return dict(row)

def named_schema(row):
 obj=json.loads(row['schema_json'])
 return {'schema_id':row['id'],'model_version_id':row['model_id'],'workflow_id':row['workflow_id'],
 'workflow_version':row['workflow_version'],'schema_hash':row['schema_hash'],'status':row['status'],'schema':obj}

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class SchemaIn(Strict):
 model_version_id:str
 workflow_id:str
 schema_definition:dict=Field(alias="schema")
class LoraIn(Strict):
 family_id:str
 name:str=Field(min_length=1,max_length=120)
 revision:str=Field(min_length=1,max_length=120)
 artifact_sha256:str
 logical_name:str
 size_bytes:int=Field(gt=0,le=2_000_000_000_000)
 min_strength:float=Field(ge=-10,le=10)
 max_strength:float=Field(ge=-10,le=10)
 trigger_words:list[str]=Field(default_factory=list,max_length=20)
class LoraSelection(Strict):
 id:str
 version:str
 enabled:bool
 model_strength:float
 clip_strength:float
 order:int=Field(ge=0,le=32)
class IntentIn(Strict):
 client_request_id:str=Field(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9._:-]+$')
 model_version_id:str
 workflow_id:str
 schema_hash:str
 parameters:dict=Field(default_factory=dict)
 seed_mode:str='fixed'
 batch_count:int=Field(default=1,ge=1,le=8)
 batch_mode:str='SAME'
 loras:list[LoraSelection]=Field(default_factory=list,max_length=16)
class PresetIn(Strict):
 loras:list[LoraSelection]=Field(default_factory=list,max_length=16)
 name:str=Field(min_length=1,max_length=120)
 model_version_id:str
 workflow_id:str
 schema_hash:str
 values:dict
 includes_prompt:bool=False
class Rename(Strict):name:str=Field(min_length=1,max_length=120)

def safe_preset(c,uid,pid):
 row=c.execute('''SELECT * FROM user_parameter_presets WHERE owner_user_id=? AND id=? AND deleted_at IS NULL''',(uid,pid)).fetchone()
 if not row:raise HTTPException(404,'Preset not found')
 return row

def preset_public(r):
 return {'id':r['id'],'name':r['name'],'model_version_id':r['model_id'],'workflow_id':r['workflow_id'],
         'workflow_version':r['workflow_version'],'schema_hash':r['schema_hash'],'values':json.loads(r['values_json']).get('values',{}),'loras':json.loads(r['values_json']).get('loras',[]),
         'includes_prompt':bool(r['includes_prompt']),'created_at':r['created_at'],'updated_at':r['updated_at']}

def validate_preset_values(schema,values,includes_prompt):
 if not isinstance(values,dict) or len(canonical(values))>32768:raise HTTPException(422,'Invalid preset fields')
 try:
  forbid(values,'values',scan_values=True)
  bykey={f['key']:f for f in schema['fields']}
  for key,value in values.items():
   if key not in bykey:raise ParameterError('unsupported_parameter','values.'+key,'Unknown preset parameter')
   if not includes_prompt and ('prompt' in key.lower() or bykey[key]['type']=='text'):
    raise ParameterError('prompt_consent_required','values.'+key,'Prompt inclusion needs consent')
   if bykey[key]['type']=='image':raise ParameterError('retention_unapproved','values.'+key,'Asset IDs cannot be persisted in Presets before retention policy approval')
   validate_value(bykey[key],value,'values.'+key)
 except ParameterError as e:client_error(e)
 return values

@router.post('/admin/parameter-schemas',status_code=201)
def create_schema(data:SchemaIn,actor=Depends(admin_mutation)):
 try:obj=validate_schema(data.schema_definition)
 except ParameterError as e:client_error(e)
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if not c.execute('SELECT 1 FROM model_versions WHERE id=?',(data.model_version_id,)).fetchone():raise HTTPException(404,'Model not found')
  g=graph(c,data.workflow_id)
  placeholders=set(re.findall(r'\{\{([A-Za-z0-9_.:-]+)\}\}',canonical(g)))
  for f in obj['fields']:
   if f['type']!='seed' and f.get('variable_key') not in placeholders:
    raise HTTPException(422,{'field_path':'schema.fields.'+f['key']+'.variable_key','message':'Binding missing in saved workflow'})
   if f['type']=='seed' and f.get('variable_key') not in placeholders:
    raise HTTPException(422,'Seed must bind to real saved workflow graph')
  all_lora_nodes={str(n) for n,node in g.items() if isinstance(node,dict) and node.get('class_type') in ('LoraLoader','LoraLoaderModelOnly')}
  if set(obj['lora_slots'].values())!=all_lora_nodes:raise HTTPException(422,'Every LoRA Loader in this graph must be explicitly bound')
  for loraid,nodeid in obj['lora_slots'].items():
   if nodeid not in g or g[nodeid].get('class_type') not in ('LoraLoader','LoraLoaderModelOnly'):
    raise HTTPException(422,'LoRA node binding is not a real Loader')
  sid=str(uuid4());h=checksum(obj)
  try:c.execute('''INSERT INTO model_parameter_schemas(id,model_id,workflow_id,workflow_version,schema_json,schema_hash,created_at) VALUES(?,?,?,?,?,?,?)''',
    (sid,data.model_version_id,data.workflow_id,graph_hash(g),canonical(obj),h,security.iso()))
  except sqlite3.IntegrityError as e:raise HTTPException(409,'Schema version already registered') from e
  registry_api.audit(c,actor,'parameter_schema.create',sid)
 return {'id':sid,'schema_hash':h,'status':'draft'}

@router.post('/admin/parameter-schemas/{schema_id}/publish')
def publish_schema(schema_id:str,actor=Depends(admin_mutation)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  row=c.execute('SELECT * FROM model_parameter_schemas WHERE id=?',(schema_id,)).fetchone()
  if not row:raise HTTPException(404,'Schema not found')
  if graph_hash(graph(c,row['workflow_id']))!=row['workflow_version']:raise HTTPException(409,'Workflow graph changed; schema requires revalidation')
  c.execute("UPDATE model_parameter_schemas SET status='published' WHERE id=? AND status='draft'",(schema_id,))
  registry_api.audit(c,actor,'parameter_schema.publish',schema_id)
 return {'id':schema_id,'status':'published','worker_verified':False}

@router.get('/models/{model_id}/parameter-schemas')
def list_model_schemas(model_id:str,actor=Depends(user)):
 with db.connect() as c:
  public_model(c,model_id)
  rows=c.execute("SELECT id,workflow_id,workflow_version,schema_hash FROM model_parameter_schemas WHERE model_id=? AND status='published' ORDER BY created_at DESC LIMIT 40",(model_id,)).fetchall()
  items=[]
  for r in rows:
   if graph_hash(graph(c,r['workflow_id']))==r['workflow_version']:
    items.append({'schema_id':r['id'],'workflow_id':r['workflow_id'],'schema_hash':r['schema_hash']})
  return {'items':items}

@router.get('/models/{model_id}/parameter-schema')
def get_schema(model_id:str,workflow_id:str,actor=Depends(user)):
 with db.connect() as c:
  public_model(c,model_id)
  row=schema_by(c,model_id,workflow_id)
  if graph_hash(graph(c,workflow_id))!=row['workflow_version']:raise HTTPException(409,'Workflow version has changed')
  return named_schema(row)

@router.post('/admin/loras',status_code=201)
def create_lora(data:LoraIn,actor=Depends(admin_mutation)):
 if not HEX.fullmatch(data.artifact_sha256) or not NAME.fullmatch(data.logical_name) or not data.logical_name.endswith('.safetensors'):
  raise HTTPException(422,'LoRA artifact must have a SHA256 and safe logical filename')
 if data.min_strength>data.max_strength or any(not isinstance(w,str) or len(w)>80 for w in data.trigger_words):raise HTTPException(422,'Invalid LoRA range/trigger words')
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if not c.execute('SELECT 1 FROM model_families WHERE id=?',(data.family_id,)).fetchone():raise HTTPException(404,'Model family not found')
  ident=str(uuid4())
  try:c.execute('''INSERT INTO lora_versions(id,family_id,name,revision,artifact_sha256,logical_name,size_bytes,min_strength,max_strength,trigger_words_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
    (ident,data.family_id,data.name,data.revision,data.artifact_sha256,data.logical_name,data.size_bytes,data.min_strength,data.max_strength,canonical(data.trigger_words),security.iso()))
  except sqlite3.IntegrityError as e:raise HTTPException(409,'Duplicate LoRA version') from e
  registry_api.audit(c,actor,'lora.create',ident)
 return {'id':ident,'status':'draft','runtime_verified':False}

@router.get('/admin/loras')
def admin_loras(actor=Depends(admin)):
 with db.connect() as c:
  return {'items':[dict(r) for r in c.execute('SELECT id,family_id,name,revision,artifact_sha256,logical_name,size_bytes,status FROM lora_versions ORDER BY created_at DESC LIMIT 100')]}

# Only test-confirmed model/Image/install pairs are shown as selectable.
VERIFIED_LORA='''EXISTS (SELECT 1 FROM model_lora_compatibility lm
 JOIN lora_installations li ON li.lora_id=lm.lora_id
 JOIN worker_images wi ON wi.id=li.image_id
 JOIN image_model_compatibility im ON im.image_id=wi.id AND im.model_id=lm.model_id
 JOIN deployment_profile_revisions rev ON rev.image_id=wi.id AND rev.status='active'
 JOIN deployment_profiles dp ON dp.active_revision_id=rev.id
 JOIN model_deployment_compatibility dc ON dc.model_id=lm.model_id AND dc.revision_id=rev.id
 WHERE lm.model_id=? AND lm.lora_id=l.id AND lm.state='tested_pass'
 AND li.state='verified' AND li.observed_sha256=l.artifact_sha256
 AND im.state='tested_pass' AND dc.state='tested_pass'
 AND wi.status='approved' AND wi.signature_status='verified')'''

def lora_records(c,model_id,include_unverified=False):
 q='''SELECT l.id,l.name,l.revision,l.logical_name,l.min_strength,l.max_strength,l.artifact_sha256,l.status,
 l.trigger_words_json,''' + ('1' if include_unverified else VERIFIED_LORA) + ''' AS compatible
 FROM lora_versions l JOIN model_versions v ON v.family_id=l.family_id AND v.id=? WHERE l.status!='deprecated' '''
 args=[model_id] if include_unverified else [model_id,model_id]
 rows=[dict(r) for r in c.execute(q,args)]
 for r in rows:
  r['trigger_words']=json.loads(r.pop('trigger_words_json'))
 return rows

@router.get('/models/{model_id}/loras')
def get_loras(model_id:str,actor=Depends(user)):
 with db.connect() as c:
  public_model(c,model_id)
  rows=lora_records(c,model_id)
  return {'items':[{'id':r['id'],'name':r['name'],'version':r['revision'],'min_strength':r['min_strength'],
     'max_strength':r['max_strength'],'trigger_words':r['trigger_words']} for r in rows if r['compatible']]}

@router.get('/presets')
def list_presets(limit:int=40,actor=Depends(user)):
 if not 1<=limit<=100:raise HTTPException(422,'Invalid page size')
 with db.connect() as c:
  rows=c.execute('''SELECT * FROM user_parameter_presets WHERE owner_user_id=? AND deleted_at IS NULL ORDER BY created_at DESC,id DESC LIMIT ?''',(actor['user_id'],limit)).fetchall()
  return {'items':[preset_public(r) for r in rows]}

@router.post('/presets',status_code=201)
def create_preset(data:PresetIn,actor=Depends(mutation)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  public_model(c,data.model_version_id)
  meta=schema_by(c,data.model_version_id,data.workflow_id,data.schema_hash)
  registered=json.loads(meta['schema_json'])
  if not data.name.strip():raise HTTPException(422,'Preset name required')
  vals=validate_preset_values(registered,data.values,data.includes_prompt)
  available=available_loras(c,data.model_version_id,data.loras)
  try:compile_lora_graph(graph(c,data.workflow_id),registered.get('lora_slots',{}),[x.model_dump() for x in data.loras],available)
  except ParameterError as e:client_error(e)
  pid=str(uuid4());moment=security.iso()
  c.execute('''INSERT INTO user_parameter_presets(id,owner_user_id,model_id,workflow_id,workflow_version,schema_hash,name,values_json,includes_prompt,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
   (pid,actor['user_id'],data.model_version_id,data.workflow_id,meta['workflow_version'],meta['schema_hash'],data.name.strip(),canonical({'values':vals,'loras':[x.model_dump() for x in data.loras]}),int(data.includes_prompt),moment,moment))
  return {'id':pid,'status':'saved'}

@router.get('/presets/{preset_id}')
def get_preset(preset_id:str,actor=Depends(user)):
 with db.connect() as c:return preset_public(safe_preset(c,actor['user_id'],preset_id))

@router.patch('/presets/{preset_id}')
def rename_preset(preset_id:str,data:Rename,actor=Depends(mutation)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');safe_preset(c,actor['user_id'],preset_id)
  if not data.name.strip():raise HTTPException(422,'Preset name required')
  c.execute('UPDATE user_parameter_presets SET name=?,updated_at=? WHERE id=? AND owner_user_id=?',(data.name.strip(),security.iso(),preset_id,actor['user_id']))
 return {'id':preset_id,'status':'renamed'}

@router.delete('/presets/{preset_id}',status_code=204)
def delete_preset(preset_id:str,actor=Depends(mutation)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');safe_preset(c,actor['user_id'],preset_id)
  c.execute('UPDATE user_parameter_presets SET deleted_at=?,updated_at=? WHERE id=? AND owner_user_id=?',(security.iso(),security.iso(),preset_id,actor['user_id']))

@router.get('/presets/{preset_id}/preview')
def preview_preset(preset_id:str,model_version_id:str,workflow_id:str,actor=Depends(user)):
 with db.connect() as c:
  row=safe_preset(c,actor['user_id'],preset_id)
  if model_version_id!=row['model_id'] or workflow_id!=row['workflow_id']:
   raise HTTPException(409,'Preset is incompatible with selected model/workflow')
  meta=schema_by(c,model_version_id,workflow_id)
  if row['schema_hash']!=meta['schema_hash'] or row['workflow_version']!=meta['workflow_version']:
   raise HTTPException(409,'Preset requires migration to changed parameter schema')
  saved=json.loads(row['values_json'])
  available=available_loras(c,model_version_id,[LoraSelection(**item) for item in saved.get('loras',[])])
  try:compile_lora_graph(graph(c,workflow_id),json.loads(meta['schema_json']).get('lora_slots',{}),saved.get('loras',[]),available)
  except ParameterError:raise HTTPException(409,'Preset LoRA compatibility changed')
  return {'preset_id':row['id'],'compatible':True,'changes':saved.get('values',{}), 'loras':saved.get('loras',[]),'applies_automatically':False}

def available_loras(c,model_id,selected):
 found={}
 if len(selected)!=len({x.id for x in selected}) or len(selected)!=len({x.order for x in selected}):
  raise HTTPException(422,{'code':'duplicate_lora','field_path':'loras','message':'Duplicate LoRA id/order'})
 for x in selected:
  r=c.execute('SELECT id,revision,logical_name,min_strength,max_strength FROM lora_versions WHERE id=?',(x.id,)).fetchone()
  if not r:raise HTTPException(422,{'field_path':'loras','message':'Unregistered LoRA'})
  verified=c.execute('SELECT '+VERIFIED_LORA+' FROM lora_versions l WHERE l.id=?',(model_id,x.id)).fetchone()[0]
  # Off selections may remain in a draft without an installed artifact.
  if x.enabled and not verified:raise HTTPException(422,{'field_path':'loras','message':'LoRA is not runtime compatible or installed'})
  found[x.id]={'version':r['revision'],'logical_name':r['logical_name'], 'min_strength':r['min_strength'],
    'max_strength':r['max_strength'],'verified':bool(verified)}
 return found

@router.post('/parameter-intents',status_code=201)
def save_intent(body:IntentIn,actor=Depends(mutation)):
 uid=actor['user_id'];payload=body.model_dump();hashreq=checksum(payload)
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  current=c.execute('''SELECT * FROM parameter_intents WHERE owner_user_id=? AND client_request_id=?''',(uid,body.client_request_id)).fetchone()
  if current:
   if current['request_hash']!=hashreq:raise HTTPException(409,'Request key was reused with different parameters')
   return {'id':current['id'],'can_submit':False,'replayed':True,'snapshot':json.loads(current['snapshot_json'])}
  public_model(c,body.model_version_id)
  meta=schema_by(c,body.model_version_id,body.workflow_id,body.schema_hash)
  g=graph(c,body.workflow_id)
  if meta['workflow_version']!=graph_hash(g):raise HTTPException(409,'Workflow changed; update form')
  try:
   selection=[x.model_dump() for x in body.loras]
   availability=available_loras(c,body.model_version_id,body.loras)
   compiled,active=compile_lora_graph(g,json.loads(meta['schema_json']).get('lora_slots',{}),selection,availability)
   param_schema=json.loads(meta['schema_json'])
   snapshot=resolve(param_schema,body.parameters,seed_mode=body.seed_mode,
      batch_count=body.batch_count,batch_mode=body.batch_mode)
   # A valid Asset ID still requires session-owner SQL checks before binding.
   from . import owner_repository
   for field in param_schema['fields']:
    if field['type']=='image' and field['key'] in snapshot['effective']:
     asset_id=snapshot['effective'][field['key']]
     row=owner_repository.asset(c,uid,asset_id)
     if not row or not row.get('mime_type','').startswith('image/'):
      raise HTTPException(404,'Private image Asset not found')
   compiled=render_resolved_graph(compiled,param_schema,snapshot)
  except ParameterError as e:client_error(e)
  # This is an immutable validated *intent*, NOT a claimed worker job or live GPU snapshot.
  snapshot.update({'model_version_id':body.model_version_id,'workflow_id':body.workflow_id,
      'workflow_version':meta['workflow_version'],'requested_loras':selection,'effective_loras':active,
      'compiled_graph_hash':checksum(compiled),'client_request_id':body.client_request_id,
      'batch_count':body.batch_count,'can_submit':False})
  identifier=str(uuid4())
  c.execute('''INSERT INTO parameter_intents(id,owner_user_id,client_request_id,request_hash,model_id,workflow_id,schema_hash,snapshot_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)''',
   (identifier,uid,body.client_request_id,hashreq,body.model_version_id,body.workflow_id,body.schema_hash,canonical(snapshot),security.iso()))
 return {'id':identifier,'replayed':False,'can_submit':False,'snapshot':snapshot}

@router.get('/parameter-intents/{intent_id}')
def get_intent(intent_id:str,actor=Depends(user)):
 with db.connect() as c:
  row=c.execute('SELECT snapshot_json FROM parameter_intents WHERE id=? AND owner_user_id=?',(intent_id,actor['user_id'])).fetchone()
  if not row:raise HTTPException(404,'Intent not found')
  return {'snapshot':json.loads(row['snapshot_json']),'can_submit':False}

@router.post('/generation/jobs')
def unavailable_generation(actor=Depends(mutation)):
 raise HTTPException(503,'Atomic owner-bound Job and Worker dispatch are not verified; no GPU action was created')
