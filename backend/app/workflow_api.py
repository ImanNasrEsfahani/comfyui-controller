"""Phase09 opt-in owner-scoped workflows and non-dispatching compile contracts.

All preview responses are redacted; stored graph is never a GPU Job. No legacy /api/workflows rewrite.
"""
from __future__ import annotations
import json,os,sqlite3
from uuid import uuid4
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,Field
from . import db,security
from .workflow_compiler import CompileError,validated,compile_graph,preview,canonical,sha

router=APIRouter(prefix='/api/v2',tags=['Versioned semantic workflows'])

def private(response:Response):response.headers['Cache-Control']='private, no-store'
def gate():
 if os.getenv('WORKFLOW_COMPILER_ENABLED','false').lower()!='true':raise HTTPException(503,'Workflow compiler disabled')
 with db.connect() as c:
  tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if not {'workflow_definitions','workflow_versions','workflow_compilations','workflow_audit'}<=tables:
   raise HTTPException(503,'Phase09 migration not applied')
def user(actor=Depends(security.require_active_user),_=Depends(gate),_cache=Depends(private)):return actor
def mutate(request:Request,actor=Depends(user)):
 security.require_csrf(request);return actor

def error(exc:CompileError):
 raise HTTPException(422,{'code':exc.code,'field_path':exc.path,'message':str(exc)}) from exc

def audited(c,actor,action,definition,version=None):
 c.execute('INSERT INTO workflow_audit VALUES(?,?,?,?,?,?)',
           (str(uuid4()),actor['user_id'],action,definition,version,security.iso()))

def definition(c,did,actor,write=False):
 d=c.execute('SELECT * FROM workflow_definitions WHERE id=?',(did,)).fetchone()
 if not d:raise HTTPException(404,'Workflow not found')
 isadmin=bool({'admin','superadmin'} & set(actor['roles']))
 if d['scope']=='user' and d['owner_user_id']!=actor['user_id'] or d['scope']=='system' and not isadmin and (write or not d['active_version_id']):
  raise HTTPException(404,'Workflow not found')
 if write and (d['scope']=='system' and not isadmin or d['scope']=='user' and d['owner_user_id']!=actor['user_id']):
  raise HTTPException(404,'Workflow not found')
 return d

def version(c,vid,actor,write=False):
 v=c.execute('SELECT * FROM workflow_versions WHERE id=?',(vid,)).fetchone()
 if not v:raise HTTPException(404,'Version not found')
 d=definition(c,v['definition_id'],actor,write)
 if d['scope']=='system' and v['status'] not in ('published','deprecated') and not set(actor['roles'])&{'admin','superadmin'}:
  raise HTTPException(404,'Version not found')
 return v,d

def ensure_model(c,mid):
 if not c.execute('SELECT 1 FROM model_versions WHERE id=?',(mid,)).fetchone():
  raise HTTPException(422,{'code':'model_not_found','field_path':'model_version_id'})

def asset_owned(c,owner,aid):
 if c.execute('SELECT 1 FROM asset_deletions WHERE owner_user_id=? AND asset_id=?',(owner,aid)).fetchone():return False
 if c.execute("SELECT 1 FROM input_assets WHERE owner_user_id=? AND asset_id=? AND ownership_state='verified'",(owner,aid)).fetchone():return True
 return c.execute('''SELECT 1 FROM job_assets a JOIN jobs j ON j.id=a.job_id
 WHERE a.owner_user_id=? AND a.asset_id=? AND a.ownership_state='verified' AND a.status='available'
 AND j.owner_user_id=? AND j.ownership_state='verified' AND j.hidden=0
 AND (j.active_attempt_id IS NULL OR a.attempt_id=j.active_attempt_id)''',(owner,aid,owner)).fetchone() is not None

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Create(Strict):
 title:str=Field(min_length=1,max_length=150)
 intent:str
 model_version_id:str
 graph:dict
 scope:str='user'
class Graph(Strict):graph:dict
class Compile(Strict):
 client_request_id:str=Field(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9._:-]+$')
 parameters:dict=Field(default_factory=dict)
class Publish(Strict):confirm:bool

@router.get('/semantic-workflow-templates')
def templates(actor=Depends(user)):
 return {'items':[{'intent':k,'label':label,'runtime_verified':False} for k,label in (
  ('text2img','Text to Image'),('img2img','Image Edit'),('multi_ref','Identity + Clothing/Pose'),('image2video','Image to Video'),('text2video','Text to Video'))]}

@router.get('/semantic-workflow-templates/{intent}')
def template(intent:str,actor=Depends(user)):
 if intent not in ('text2img','img2img','multi_ref','image2video','text2video'):raise HTTPException(404,'Template not found')
 location=Path(__file__).parent/'workflow_templates'/f'{intent}.json'
 obj=json.loads(location.read_text(encoding='utf-8'))
 try:spec=validated(obj)
 except CompileError as e:error(e)
 return {'intent':intent,'graph':spec,'runtime_verified':False,'dispatch_allowed':False}


@router.post('/semantic-workflows',status_code=201)
def create(data:Create,actor=Depends(mutate)):
 if data.scope!='user' and not (data.scope=='system' and 'superadmin' in actor['roles']):raise HTTPException(403,'System workflows need superadmin')
 try:s=validated(data.graph)
 except CompileError as e:error(e)
 if data.intent!=s['intent']:raise HTTPException(422,'Intent differs from validated graph')
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');ensure_model(c,data.model_version_id)
  did,vid=str(uuid4()),str(uuid4());now=security.iso()
  c.execute('INSERT INTO workflow_definitions VALUES(?,?,?,?,?,?,?)',
            (did,data.title.strip(),data.intent,data.scope,actor['user_id'] if data.scope=='user' else None,None,now))
  c.execute('''INSERT INTO workflow_versions(id,definition_id,version,model_version_id,status,graph_json,graph_checksum,created_by,created_at)
       VALUES (?,?,?,?,?,?,?,?,?)''',(vid,did,1,data.model_version_id,'draft',canonical(s),sha(s),actor['user_id'],now))
  audited(c,actor,'workflow.create',did,vid)
 return {'id':did,'version_id':vid,'status':'draft'}

@router.get('/semantic-workflows')
def list_mine(actor=Depends(user)):
 with db.connect() as c:
  rows=c.execute('''SELECT id,title,intent,scope,active_version_id FROM workflow_definitions
    WHERE owner_user_id=? OR (scope='system' AND active_version_id IS NOT NULL)
    ORDER BY created_at DESC LIMIT 100''',(actor['user_id'],)).fetchall()
  return {'items':[dict(x) for x in rows]}

@router.get('/semantic-workflows/{definition_id}/versions')
def versions(definition_id:str,actor=Depends(user)):
 with db.connect() as c:
  d=definition(c,definition_id,actor)
  rows=c.execute('''SELECT id,version,model_version_id,status,graph_checksum,created_at,published_at
   FROM workflow_versions WHERE definition_id=? ORDER BY version DESC''',(d['id'],)).fetchall()
  if d['scope']=='system' and not set(actor['roles'])&{'admin','superadmin'}:
   rows=[r for r in rows if r['status']=='published']
  return {'active_version_id':d['active_version_id'],'items':[dict(x) for x in rows]}

@router.get('/semantic-workflow-versions/{version_id}')
def get_version(version_id:str,actor=Depends(user)):
 with db.connect() as c:
  v,d=version(c,version_id,actor)
  # Never return graph or user-content in an admin/system listing by default.
  return {'id':v['id'],'definition_id':d['id'],'version':v['version'],'status':v['status'],
          'model_version_id':v['model_version_id'],'graph_checksum':v['graph_checksum'],
          'active':d['active_version_id']==v['id'],
          'input_schema':json.loads(v['graph_json'])['inputs']}

@router.post('/semantic-workflows/{definition_id}/versions',status_code=201)
def clone(definition_id:str,actor=Depends(mutate)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');d=definition(c,definition_id,actor,True)
  base=c.execute('SELECT * FROM workflow_versions WHERE definition_id=? ORDER BY version DESC LIMIT 1',(definition_id,)).fetchone()
  vid=str(uuid4());n=base['version']+1
  c.execute('''INSERT INTO workflow_versions(id,definition_id,version,model_version_id,graph_json,graph_checksum,created_by,created_at)
    VALUES(?,?,?,?,?,?,?,?)''',(vid,definition_id,n,base['model_version_id'],base['graph_json'],base['graph_checksum'],actor['user_id'],security.iso()))
  audited(c,actor,'workflow.clone',definition_id,vid)
 return {'id':vid,'version':n,'status':'draft'}

@router.patch('/semantic-workflow-versions/{version_id}/draft')
def update_draft(version_id:str,data:Graph,actor=Depends(mutate)):
 try:s=validated(data.graph)
 except CompileError as e:error(e)
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');v,d=version(c,version_id,actor,True)
  if v['status'] not in ('draft','validated'):raise HTTPException(409,'Published version is immutable; clone first')
  if s['intent']!=d['intent']:raise HTTPException(422,'Intent cannot be changed on existing definition')
  c.execute("UPDATE workflow_versions SET graph_json=?,graph_checksum=?,status='draft',compiled_template_json=NULL,compiled_hash=NULL,validated_at=NULL WHERE id=?",
    (canonical(s),sha(s),version_id))
  audited(c,actor,'workflow.draft.update',d['id'],version_id)
 return {'id':version_id,'status':'draft','checksum':sha(s)}

@router.post('/semantic-workflow-versions/{version_id}/validate')
def validate_version(version_id:str,actor=Depends(mutate)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');v,d=version(c,version_id,actor,True)
  if v['status'] in ('published','deprecated'):raise HTTPException(409,'Published version immutable')
  try:s=validated(json.loads(v['graph_json']))
  except CompileError as e:error(e)
  h=sha(s)
  if h!=v['graph_checksum']:raise HTTPException(409,'Graph checksum mismatch')
  # Trusted catalog lacks runtime inventory. This marks only structural validation.
  template={'spec_hash':h,'node_kinds':sorted({x['kind'] for x in s['nodes']}),'runtime_verified':False}
  c.execute("UPDATE workflow_versions SET status='validated',validated_at=?,compiled_template_json=?,compiled_hash=? WHERE id=?",
    (security.iso(),canonical(template),sha(template),version_id))
  audited(c,actor,'workflow.validate',d['id'],version_id)
 return {'id':version_id,'status':'validated','checksum':h,'runtime_verified':False,'dispatch_allowed':False}

@router.post('/semantic-workflow-versions/{version_id}/compile-preview',status_code=201)
def compile_preview(version_id:str,data:Compile,actor=Depends(mutate)):
 payload={'version_id':version_id,'client_request_id':data.client_request_id,'parameters':data.parameters}
 request_hash=sha(payload)
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');v,d=version(c,version_id,actor)
  if v['status'] not in ('validated','published'):raise HTTPException(409,'Validate draft first')
  old=c.execute('SELECT id,request_hash,graph_hash FROM workflow_compilations WHERE owner_user_id=? AND client_request_id=?',
                (actor['user_id'],data.client_request_id)).fetchone()
  if old:
   if old['request_hash']!=request_hash:raise HTTPException(409,'Idempotency key conflict')
   return {'id':old['id'],'graph_hash':old['graph_hash'],'replayed':True,'job_created':False,'dispatch_allowed':False}
  try:
   result=compile_graph(json.loads(v['graph_json']),data.parameters,
       authorize_asset=lambda aid:asset_owned(c,actor['user_id'],aid),model_id=v['model_version_id'])
  except CompileError as e:error(e)
  cid=str(uuid4()); now=security.iso()
  c.execute('''INSERT INTO workflow_compilations VALUES(?,?,?,?,?,?,?,?,?,?)''',
    (cid,actor['user_id'],data.client_request_id,request_hash,version_id,v['model_version_id'],
     canonical(result['graph']),result['graph_hash'],canonical({'workflow_version_id':version_id,
     'workflow_spec_hash':result['workflow_spec_hash'],'inputs':data.parameters,'model_version_id':v['model_version_id']}),now))
  audited(c,actor,'workflow.compile.preview',d['id'],version_id)
 return {'id':cid,'replayed':False,'job_created':False,**preview(result)}

@router.post('/semantic-workflow-versions/{version_id}/publish')
def publish(version_id:str,data:Publish,actor=Depends(mutate)):
 if not data.confirm:raise HTTPException(422,'Explicit confirmation required')
 if 'superadmin' not in actor['roles']:raise HTTPException(403,'Publishing requires approved superadmin policy')
 if os.getenv('WORKFLOW_PUBLISH_METADATA_ENABLED','false').lower()!='true':
  raise HTTPException(503,'Publishing blocked pending Phase07 runtime and approval policy')
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');v,d=version(c,version_id,actor,True)
  if v['status']!='validated':raise HTTPException(409,'Only validated draft can be published')
  if d['scope']!='system':raise HTTPException(403,'User drafts cannot be published globally')
  verified=c.execute('''SELECT 1 FROM model_versions m
 JOIN model_deployment_compatibility dc ON dc.model_id=m.id AND dc.state='tested_pass'
 JOIN deployment_profile_revisions dr ON dr.id=dc.revision_id AND dr.status='active'
 JOIN worker_images wi ON wi.id=dr.image_id AND wi.status='approved' AND wi.signature_status='verified'
 JOIN image_model_compatibility ic ON ic.image_id=wi.id AND ic.model_id=m.id AND ic.state='tested_pass'
 WHERE m.id=? AND m.status='ready' LIMIT 1''',(v['model_version_id'],)).fetchone()
  if not verified:raise HTTPException(409,'No verified active Worker/Image/Model pair; no publish')
  c.execute("UPDATE workflow_versions SET status='published',published_at=? WHERE id=? AND status='validated'",(security.iso(),version_id))
  c.execute('UPDATE workflow_definitions SET active_version_id=? WHERE id=?',(version_id,d['id']))
  audited(c,actor,'workflow.publish.metadata',d['id'],version_id)
 return {'id':version_id,'status':'published','active_version_id':version_id,
         'gpu_deployed':False,'job_create_enabled':False}
