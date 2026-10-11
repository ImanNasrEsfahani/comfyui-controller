"""Opt-in Phase10 workflow Studio, layered over Phase09's authoritative compiler.

No provider calls. Studio state is only an editor draft; published graph and old
job snapshots are not altered. No browser-supplied class_type or executable code.
"""
from __future__ import annotations
import json,os,re,sys
from uuid import uuid4
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,Field
from . import db,security
phase09=sys.modules[__package__ + '.workflow_api']
from .workflow_compiler import (NODE_KINDS,MAX_EDGES,MAX_NODES,SAFE_ID,
                                CompileError,validated,canonical,sha)

router=APIRouter(prefix='/studio',tags=['Workflow Studio Editor'])

def gate():
 if os.getenv('WORKFLOW_STUDIO_ENABLED','false').lower()!='true':
  raise HTTPException(503,'Workflow Studio is disabled')
 phase09.gate()
 with db.connect() as c:
  if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='studio_drafts'").fetchone():
   raise HTTPException(503,'Phase10 migration is not applied')

def editor(actor=Depends(security.require_active_user),_=Depends(gate),_cache=Depends(phase09.private)):
 roles=set(actor.get('roles',[]))
 if not roles&{'admin','superadmin'} and not ('power_user' in roles and
            os.getenv('WORKFLOW_STUDIO_POWER_USERS_ENABLED','false').lower()=='true'):
  raise HTTPException(403,'Studio requires an explicitly authorized role')
 return actor

def write(request:Request,actor=Depends(editor)):
 security.require_csrf(request)
 return actor

def guarded(c,vid,actor,write=False):
 v,d=phase09.version(c,vid,actor,write)
 if d['scope']=='system' and 'superadmin' not in actor['roles'] and write:
  raise HTTPException(403,'Only superadmin may modify system Workflow')
 return v,d

def strict_graph(g):
 """Allow incomplete *typed* working drafts, never malformed edges/code/cycles.

 Publishing/compiling always uses Phase09 validated(g), not this validator.
 """
 if not isinstance(g,dict) or set(g)!={'intent','nodes','edges','inputs','outputs'}:
  raise CompileError('invalid_graph','graph','Strict semantic graph keys required')
 if g['intent'] not in ('text2img','img2img','multi_ref','image2video','text2video'):
  raise CompileError('invalid_intent','intent','Unavailable workflow intent')
 nodes,edges,inputs,outputs=[g[x] for x in ('nodes','edges','inputs','outputs')]
 if not all(isinstance(x,list) for x in (nodes,edges,inputs,outputs)):
  raise CompileError('invalid_graph','graph','Graph arrays required')
 if len(nodes)>MAX_NODES or len(edges)>MAX_EDGES or len(inputs)>64 or len(outputs)>16:
  raise CompileError('graph_size','graph','Graph limits exceeded')
 ids={}
 for idx,n in enumerate(nodes):
  if not isinstance(n,dict) or set(n)!={'id','kind'} or not isinstance(n['id'],str) or not SAFE_ID.fullmatch(n['id']) or n['id'] in ids or not isinstance(n['kind'],str) or n['kind'] not in NODE_KINDS:
   raise CompileError('invalid_node',f'nodes.{idx}','Invalid or unapproved semantic node')
  ids[n['id']]=n['kind']
 occupied=set();direct={nid:set() for nid in ids}
 for idx,e in enumerate(edges):
  p=f'edges.{idx}'
  if not isinstance(e,dict) or set(e)!={'from','out','to','in'} or not all(isinstance(e[z],str) for z in ('from','out','to','in')) or e['from'] not in ids or e['to'] not in ids:
   raise CompileError('invalid_edge',p,'Invalid edge endpoints')
  src,_,source_ports,_=NODE_KINDS[ids[e['from']]]
  _,dest_ports,_,_=NODE_KINDS[ids[e['to']]]
  if e['out'] not in source_ports or e['in'] not in dest_ports:
   raise CompileError('invalid_port',p,'Port does not exist on approved node')
  source_type=source_ports[e['out']];dest_type=dest_ports[e['in']]
  if source_type!=dest_type and not (source_type=='integer' and dest_type=='number'):
   raise CompileError('port_type',p,'Incompatible typed ports')
  target=(e['to'],e['in'])
  if target in occupied:raise CompileError('duplicate_binding',p,'Port already bound')
  occupied.add(target);direct[e['from']].add(e['to'])
 for idx,i in enumerate(inputs):
  p=f'inputs.{idx}'
  if not isinstance(i,dict) or set(i)!={'key','type','role','node','port','required'} or not isinstance(i['key'],str) or not SAFE_ID.fullmatch(i['key']) or not isinstance(i['role'],str) or not SAFE_ID.fullmatch(i['role']) or not isinstance(i['required'],bool) or not all(isinstance(i[z],str) for z in ('node','port','type')) or i['node'] not in ids:
   raise CompileError('invalid_input',p,'Invalid input binding')
  ports=NODE_KINDS[ids[i['node']]][1]
  if i['port'] not in ports or ports[i['port']]!=i['type']:
   raise CompileError('input_type',p,'Unsupported typed input')
  target=(i['node'],i['port'])
  if target in occupied or any(other['key']==i['key'] for other in inputs[:idx]):
   raise CompileError('duplicate_binding',p,'Input key or target reused')
  occupied.add(target)
 for idx,out in enumerate(outputs):
  if not isinstance(out,dict) or set(out)!={'node','media_type'} or not isinstance(out['node'],str) or out['node'] not in ids or ids[out['node']] not in ('image_output','video_output') or out['media_type']!=('image' if ids[out['node']]=='image_output' else 'video'):
   raise CompileError('invalid_output',f'outputs.{idx}','Invalid output binding')
 visited=set();active=set()
 def walk(n):
  if n in active:raise CompileError('graph_cycle','edges','Graph contains a cycle')
  if n in visited:return
  active.add(n)
  for dest in direct[n]:walk(dest)
  active.remove(n);visited.add(n)
 for nid in ids:walk(nid)
 return g

def safe_layout(layout,ids):
 if not isinstance(layout,dict) or set(layout)-set(ids):raise HTTPException(422,'Layout must reference only graph nodes')
 result={}
 for k,v in layout.items():
  if not isinstance(v,dict) or set(v)!={'x','y'} or any(isinstance(v[z],bool) or not isinstance(v[z],(int,float)) or not -20000<=v[z]<=20000 for z in ('x','y')):
   raise HTTPException(422,'Invalid node position')
  result[k]={'x':round(float(v['x']),2),'y':round(float(v['y']),2)}
 return result

def safe_viewport(value):
 if not isinstance(value,dict) or set(value)!={'x','y','zoom'} or any(isinstance(value[x],bool) or not isinstance(value[x],(int,float)) for x in ('x','y','zoom')) or not -20000<=value['x']<=20000 or not -20000<=value['y']<=20000 or not .25<=value['zoom']<=2:
  raise HTTPException(422,'Invalid viewport')
 return {'x':round(value['x'],2),'y':round(value['y'],2),'zoom':round(value['zoom'],3)}

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Draft(Strict):
 revision:int=Field(ge=0)
 graph:dict
 layout:dict=Field(default_factory=dict)
 viewport:dict=Field(default_factory=lambda:{'x':0,'y':0,'zoom':1})
class RevisionRequest(Strict):revision:int=Field(ge=0)
class Restore(Strict):source_version_id:str=Field(min_length=1,max_length=96)
class Unpublish(Strict):confirm:bool

def load(c,v):
 row=c.execute('SELECT * FROM studio_drafts WHERE version_id=?',(v['id'],)).fetchone()
 if row:return {'revision':row['revision'],'graph':json.loads(row['graph_json']),
  'layout':json.loads(row['layout_json']),'viewport':json.loads(row['viewport_json']),
  'base_checksum':row['base_checksum']}
 return {'revision':0,'graph':json.loads(v['graph_json']),'layout':{},
  'viewport':{'x':0,'y':0,'zoom':1},'base_checksum':v['graph_checksum']}

@router.get('/nodes')
def nodes(actor=Depends(editor)):
 return {'items':[{'kind':k,'inputs':dict(v[1]),'outputs':dict(v[2]),'runtime_verified':False}
                   for k,v in NODE_KINDS.items() if not v[0].startswith('UNVERIFIED_') or k in ('multi_reference','video_generation','video_output')],
         'worker_inventory_verified':False,'dispatch_allowed':False}

@router.get('/versions/{vid}/editor')
def read(vid:str,response:Response,actor=Depends(editor)):
 response.headers['Cache-Control']='private, no-store'
 with db.connect() as c:
  v,d=guarded(c,vid,actor)
  if v['status'] in ('published','deprecated'):
   data={'revision':0,'graph':json.loads(v['graph_json']),'layout':{},'viewport':{'x':0,'y':0,'zoom':1},'base_checksum':v['graph_checksum']}
  else:data=load(c,v)
  return {**data,'version_id':vid,'definition_id':d['id'],'title':d['title'],'status':v['status'],
          'model_version_id':v['model_version_id'],'editable':v['status'] in ('draft','validated'),
          'runtime_verified':False}

@router.patch('/versions/{vid}/draft')
def save(vid:str,data:Draft,actor=Depends(write)):
 try:graph=strict_graph(data.graph)
 except CompileError as e:phase09.error(e)
 layout=safe_layout(data.layout,{x['id'] for x in graph['nodes']});viewport=safe_viewport(data.viewport)
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');v,d=guarded(c,vid,actor,True)
  if v['status'] not in ('draft','validated'):raise HTTPException(409,'Published workflow cannot be edited')
  existing=c.execute('SELECT revision,base_checksum FROM studio_drafts WHERE version_id=?',(vid,)).fetchone()
  actual=existing['revision'] if existing else 0
  if actual!=data.revision:raise HTTPException(409,{'code':'stale_revision','current_revision':actual,'action':'reload_or_clone'})
  base=existing['base_checksum'] if existing else v['graph_checksum']
  if base!=v['graph_checksum']:raise HTTPException(409,'Workflow changed outside Studio; reload and resolve conflict')
  nextrev=actual+1
  c.execute('''INSERT INTO studio_drafts(version_id,revision,graph_json,layout_json,viewport_json,base_checksum,editor_user_id,updated_at)
       VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(version_id) DO UPDATE SET
       revision=excluded.revision,graph_json=excluded.graph_json,layout_json=excluded.layout_json,
       viewport_json=excluded.viewport_json,updated_at=excluded.updated_at''',
       (vid,nextrev,canonical(graph),canonical(layout),canonical(viewport),base,actor['user_id'],security.iso()))
  phase09.audited(c,actor,'studio.draft.saved',d['id'],vid)
 return {'revision':nextrev,'checksum':sha(graph),'saved':True,'gpu_dispatched':False}

@router.post('/versions/{vid}/validate')
def validate(vid:str,data:RevisionRequest,actor=Depends(write)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');v,d=guarded(c,vid,actor,True)
  if v['status'] not in ('draft','validated'):raise HTTPException(409,'Immutable version')
  draft=load(c,v)
  if draft['revision']!=data.revision:raise HTTPException(409,{'code':'stale_revision','current_revision':draft['revision']})
  if draft['base_checksum']!=v['graph_checksum']:raise HTTPException(409,'Phase09 graph changed independently')
  try:graph=validated(draft['graph'])
  except CompileError as e:phase09.error(e)
  h=sha(graph);template={'spec_hash':h,'node_kinds':sorted({n['kind'] for n in graph['nodes']}),'runtime_verified':False}
  c.execute('''UPDATE workflow_versions SET graph_json=?,graph_checksum=?,status='validated',
     validated_at=?,compiled_template_json=?,compiled_hash=? WHERE id=?''',
     (canonical(graph),h,security.iso(),canonical(template),sha(template),vid))
  c.execute('UPDATE studio_drafts SET base_checksum=? WHERE version_id=?',(h,vid))
  phase09.audited(c,actor,'studio.draft.validated',d['id'],vid)
 return {'revision':data.revision,'checksum':h,'validated':True,'runtime_verified':False,'dispatch_allowed':False}

@router.get('/versions/{vid}/compile-preview')
def inspect_compilation(vid:str,response:Response,actor=Depends(editor)):
 response.headers['Cache-Control']='private, no-store'
 with db.connect() as c:
  v,d=guarded(c,vid,actor)
  if v['status'] not in ('validated','published') or not v['compiled_hash']:
   raise HTTPException(409,'Validate complete draft before compile preview')
  draft=load(c,v)
  if draft['base_checksum']!=v['graph_checksum'] or sha(draft['graph'])!=v['graph_checksum']:
   raise HTTPException(409,'Editor draft has unpublished/unvalidated changes')
  try:spec=validated(json.loads(v['graph_json']))
  except CompileError as e:phase09.error(e)
  # Structural summary only. Never expose graph runtime payload, input values,
  # user prompt, asset IDs, object storage keys, or signed URLs.
  return {'workflow_version_id':vid,'graph_checksum':v['graph_checksum'],
          'compiler_template_hash':v['compiled_hash'],
          'node_kinds':sorted({n['kind'] for n in spec['nodes']}),
          'node_count':len(spec['nodes']),'edge_count':len(spec['edges']),
          'inputs':[{'key':x['key'],'type':x['type'],'role':x['role']} for x in spec['inputs']],
          'runtime_verified':False,'dispatch_allowed':False,'gpu_job_created':False}

@router.post('/versions/{vid}/publish')
def publish(vid:str,data:Unpublish,actor=Depends(write)):
 with db.connect() as c:
  v,d=guarded(c,vid,actor,True);draft=load(c,v)
  if d['scope']!='system' or 'superadmin' not in actor['roles']:raise HTTPException(403,'System publish requires superadmin')
  if draft['base_checksum']!=v['graph_checksum'] or sha(draft['graph'])!=v['graph_checksum']:
   raise HTTPException(409,'Unsynchronized Studio edits; validate before publishing')
 # Phase09 keeps the only authoritative publish implementation, including runtime gate.
 return phase09.publish(vid,phase09.Publish(confirm=data.confirm),actor=actor)

@router.post('/versions/{vid}/restore',status_code=201)
def restore(vid:str,data:Restore,actor=Depends(write)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');target,d=guarded(c,vid,actor,True)
  source,source_d=guarded(c,data.source_version_id,actor)
  if source_d['id']!=d['id']:raise HTTPException(422,'Restore requires the same workflow')
  n=c.execute('SELECT COALESCE(MAX(version),0)+1 FROM workflow_versions WHERE definition_id=?',(d['id'],)).fetchone()[0]
  new_id=str(uuid4())
  c.execute('''INSERT INTO workflow_versions(id,definition_id,version,model_version_id,status,graph_json,graph_checksum,created_by,created_at)
   VALUES(?,?,?,?,?,?,?,?,?)''',(new_id,d['id'],n,source['model_version_id'],'draft',source['graph_json'],source['graph_checksum'],actor['user_id'],security.iso()))
  phase09.audited(c,actor,'studio.restored_as_new_draft',d['id'],new_id)
 return {'version_id':new_id,'version':n,'status':'draft','source_version_id':source['id']}

@router.post('/workflows/{did}/unpublish')
def unpublish(did:str,data:Unpublish,actor=Depends(write)):
 if not data.confirm:raise HTTPException(422,'Explicit confirmation required')
 if 'superadmin' not in actor['roles']:raise HTTPException(403,'Unpublishing system workflows requires superadmin')
 if os.getenv('WORKFLOW_UNPUBLISH_ENABLED','false').lower()!='true':raise HTTPException(503,'Unpublish pending approved policy')
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');d=phase09.definition(c,did,actor,True)
  if d['scope']!='system':raise HTTPException(403,'Only global workflow publication is managed here')
  c.execute('UPDATE workflow_definitions SET active_version_id=NULL WHERE id=?',(did,))
  phase09.audited(c,actor,'studio.unpublished.pointer',did,d['active_version_id'])
 return {'unpublished':True,'old_versions_preserved':True,'gpu_dispatched':False}
