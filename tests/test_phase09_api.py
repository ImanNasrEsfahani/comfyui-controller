"""Offline FastAPI TestClient + SQLite fixture; no production credentials, GPU or R2."""
import sys,sqlite3,tempfile,unittest,os,types,importlib
from pathlib import Path
from fastapi import FastAPI,Request,HTTPException
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.migrations import phase09
from test_phase09_compiler import sample,params

class APITest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.connections=[];self.path=Path(self.tmp.name)/'test.sqlite'
  c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
  for sql in [
    'CREATE TABLE users(id TEXT PRIMARY KEY)',
    'CREATE TABLE model_versions(id TEXT PRIMARY KEY,status TEXT)',
    'CREATE TABLE workflows(id TEXT PRIMARY KEY)',
    'CREATE TABLE jobs(id TEXT PRIMARY KEY,owner_user_id TEXT,ownership_state TEXT,hidden INTEGER,active_attempt_id TEXT)',
    'CREATE TABLE input_assets(asset_id TEXT,owner_user_id TEXT,ownership_state TEXT)',
    'CREATE TABLE job_assets(asset_id TEXT,owner_user_id TEXT,ownership_state TEXT,status TEXT,job_id TEXT,attempt_id TEXT)',
    'CREATE TABLE asset_deletions(asset_id TEXT,owner_user_id TEXT)',
    'CREATE TABLE model_deployment_compatibility(model_id TEXT,revision_id TEXT,state TEXT)',
    'CREATE TABLE schema_migrations(revision TEXT PRIMARY KEY,applied_at TEXT,checksum TEXT)',
    'CREATE TABLE deployment_profile_revisions(id TEXT PRIMARY KEY,image_id TEXT,status TEXT)',
    'CREATE TABLE worker_images(id TEXT PRIMARY KEY,status TEXT,signature_status TEXT)',
    'CREATE TABLE image_model_compatibility(image_id TEXT,model_id TEXT,state TEXT)',
   ]:c.execute(sql)
  c.executemany('INSERT INTO users VALUES(?)',[('A',),('B',),('ADMIN',)])
  c.execute("INSERT INTO model_versions VALUES('model-1','ready')")
  c.execute("INSERT INTO workflows VALUES('legacy1')")
  c.executemany('INSERT INTO input_assets VALUES(?,?,?)',[('assetA','A','verified'),('assetB','B','verified')])
  c.commit();self.assertTrue(phase09.migrate(c));self.assertFalse(phase09.migrate(c));c.close()
  # Inject only test-only DB/auth isolation dependencies into namespace; run real router code.
  from backend import app as pkg
  self.prevdb=sys.modules.get('backend.app.db');self.prevsecurity=sys.modules.get('backend.app.security');self.prevapi=sys.modules.get('backend.app.workflow_api')
  self.db=types.ModuleType('backend.app.db');self.security=types.ModuleType('backend.app.security')
  def connect():
   cx=sqlite3.connect(self.path,timeout=5,check_same_thread=False);cx.row_factory=sqlite3.Row;cx.execute('PRAGMA foreign_keys=ON');self.connections.append(cx);return cx
  self.db.connect=connect
  def current(req:Request):
   k=req.headers.get('x-mock-principal')
   if k not in ('A','B','ADMIN'):raise HTTPException(401,'No valid test session')
   return {'user_id':k,'roles':['superadmin'] if k=='ADMIN' else ['user']}
  def csrf(req:Request):
   if req.headers.get('x-mock-csrf')!='fixture-valid':raise HTTPException(403,'CSRF')
  self.security.require_active_user=current;self.security.require_csrf=csrf
  self.security.iso=lambda:'2026-10-11T15:00:00+00:00'
  sys.modules['backend.app.db']=self.db;sys.modules['backend.app.security']=self.security
  pkg.db=self.db;pkg.security=self.security
  sys.modules.pop('backend.app.workflow_api',None)
  self.api=importlib.import_module('backend.app.workflow_api')
  self.app=FastAPI();self.app.include_router(self.api.router)
  self.client=TestClient(self.app)
  self.old_env=os.environ.get('WORKFLOW_COMPILER_ENABLED');os.environ['WORKFLOW_COMPILER_ENABLED']='true'
  self.old_publish=os.environ.get('WORKFLOW_PUBLISH_METADATA_ENABLED');os.environ['WORKFLOW_PUBLISH_METADATA_ENABLED']='false'
 def tearDown(self):
  for k,v in [('backend.app.db',self.prevdb),('backend.app.security',self.prevsecurity),('backend.app.workflow_api',self.prevapi)]:
   if v is None:sys.modules.pop(k,None)
   else:sys.modules[k]=v
  from backend import app as pkg
  if self.prevdb is not None:pkg.db=self.prevdb
  if self.prevsecurity is not None:pkg.security=self.prevsecurity
  for k,v in [('WORKFLOW_COMPILER_ENABLED',self.old_env),('WORKFLOW_PUBLISH_METADATA_ENABLED',self.old_publish)]:
   if v is None:os.environ.pop(k,None)
   else:os.environ[k]=v
  self.client.close();
  for cx in self.connections:cx.close()
  self.tmp.cleanup()
 def call(self,m,path,who='A',csrf=True,body=None):
  h={'x-mock-principal':who}
  if csrf:h['x-mock-csrf']='fixture-valid'
  return self.client.request(m,'/api/v2'+path,headers=h,json=body)
 def new(self,scope='user',who='A',kind='text2img'):
  p={'title':'Test Workflow','intent':kind,'model_version_id':'model-1','graph':sample(kind),'scope':scope}
  r=self.call('POST','/semantic-workflows',who=who,body=p)
  self.assertEqual(r.status_code,201,r.text);return r.json()
 def test_create_validate_compile_and_replay(self):
  v=self.new();vid=v['version_id']
  self.assertEqual(self.call('POST',f'/semantic-workflow-versions/{vid}/validate').status_code,200)
  body={'client_request_id':'same-key','parameters':params('text2img')}
  a=self.call('POST',f'/semantic-workflow-versions/{vid}/compile-preview',body=body)
  self.assertEqual(a.status_code,201,a.text);self.assertFalse(a.json()['job_created'])
  self.assertNotIn('a tree',a.text);self.assertNotIn('18446744073709551615',a.text)
  b=self.call('POST',f'/semantic-workflow-versions/{vid}/compile-preview',body=body)
  self.assertTrue(b.json()['replayed']);self.assertEqual(a.json()['graph_hash'],b.json()['graph_hash'])
  body['parameters']['prompt']='the second prompt'
  conflict=self.call('POST',f'/semantic-workflow-versions/{vid}/compile-preview',body=body)
  self.assertEqual(conflict.status_code,409)
 def test_template_endpoint_is_structurally_real_and_nonrunning(self):
  for kind in ('text2img','img2img','multi_ref','image2video','text2video'):
   r=self.call('GET',f'/semantic-workflow-templates/{kind}')
   self.assertEqual(r.status_code,200,(kind,r.text))
   self.assertFalse(r.json()['dispatch_allowed'])
   self.assertEqual(r.json()['graph']['intent'],kind)
  self.assertEqual(self.call('GET','/semantic-workflow-templates/execute_shell').status_code,404)
 def test_owner_isolation(self):
  v=self.new();did,vid=v['id'],v['version_id']
  for u in ['B']:
   self.assertEqual(self.call('GET',f'/semantic-workflows/{did}/versions',who=u).status_code,404)
   self.assertEqual(self.call('GET',f'/semantic-workflow-versions/{vid}',who=u).status_code,404)
   self.assertEqual(self.call('POST',f'/semantic-workflow-versions/{vid}/validate',who=u).status_code,404)
   self.assertEqual(self.call('POST',f'/semantic-workflow-versions/{vid}/compile-preview',who=u,body={'client_request_id':'x','parameters':params('text2img')}).status_code,404)
 def test_cross_user_asset_is_denied(self):
  v=self.new(kind='img2img');vid=v['version_id']
  self.call('POST',f'/semantic-workflow-versions/{vid}/validate')
  p=params('img2img');p['source_image']='assetB'
  r=self.call('POST',f'/semantic-workflow-versions/{vid}/compile-preview',body={'client_request_id':'asset-leak','parameters':p})
  self.assertEqual(r.status_code,422,r.text);self.assertEqual(r.json()['detail']['code'],'asset_access_denied')
  with self.db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM workflow_compilations').fetchone()[0],0)
 def test_csrf_required(self):
  r=self.call('POST','/semantic-workflows',csrf=False,body={'title':'x','intent':'text2img','graph':sample('text2img'),'scope':'user','model_version_id':'model-1'})
  self.assertEqual(r.status_code,403)
 def test_anonymous_denied(self):
  self.assertEqual(self.call('GET','/semantic-workflows',who='invalid').status_code,401)
 def test_feature_gate(self):
  os.environ['WORKFLOW_COMPILER_ENABLED']='false'
  self.assertEqual(self.call('GET','/semantic-workflows').status_code,503)
 def test_validate_unsafe_node_before_writing(self):
  s=sample('text2img');s['nodes'][0]['kind']='PythonExec'
  r=self.call('POST','/semantic-workflows',body={'title':'bad','intent':'text2img','model_version_id':'model-1','graph':s,'scope':'user'})
  self.assertEqual(r.status_code,422);self.assertEqual(r.json()['detail']['code'],'unknown_node')
 def test_draft_clone_preserves_prior_hash(self):
  x=self.new();self.call('POST',f"/semantic-workflow-versions/{x['version_id']}/validate")
  r=self.call('POST',f"/semantic-workflows/{x['id']}/versions")
  self.assertEqual(r.status_code,201,r.text);nv=r.json()['id']
  changed=sample('text2img');changed['inputs'][0]['role']='newinstruction'
  self.assertEqual(self.call('PATCH',f'/semantic-workflow-versions/{nv}/draft',body={'graph':changed}).status_code,200)
  with self.db.connect() as c:
   old=c.execute('SELECT graph_checksum FROM workflow_versions WHERE id=?',(x['version_id'],)).fetchone()[0]
   newer=c.execute('SELECT graph_checksum FROM workflow_versions WHERE id=?',(nv,)).fetchone()[0]
  self.assertNotEqual(old,newer)
 def test_publish_blocked_by_default(self):
  x=self.new('system','ADMIN');vid=x['version_id'];self.call('POST',f'/semantic-workflow-versions/{vid}/validate',who='ADMIN')
  r=self.call('POST',f'/semantic-workflow-versions/{vid}/publish',who='ADMIN',body={'confirm':True})
  self.assertEqual(r.status_code,503)
  with self.db.connect() as c:self.assertIsNone(c.execute('SELECT active_version_id FROM workflow_definitions WHERE id=?',(x['id'],)).fetchone()[0])
 def test_no_fake_compatibility(self):
  x=self.new('system','ADMIN');vid=x['version_id'];self.call('POST',f'/semantic-workflow-versions/{vid}/validate',who='ADMIN')
  os.environ['WORKFLOW_PUBLISH_METADATA_ENABLED']='true'
  r=self.call('POST',f'/semantic-workflow-versions/{vid}/publish',who='ADMIN',body={'confirm':True})
  self.assertEqual(r.status_code,409)
 def test_synthetic_metadata_publish_immutable(self):
  x=self.new('system','ADMIN');vid=x['version_id'];self.call('POST',f'/semantic-workflow-versions/{vid}/validate',who='ADMIN')
  os.environ['WORKFLOW_PUBLISH_METADATA_ENABLED']='true'
  with self.db.connect() as c:
   c.execute("INSERT INTO worker_images VALUES('image-1','approved','verified')")
   c.execute("INSERT INTO deployment_profile_revisions VALUES('rev-1','image-1','active')")
   c.execute("INSERT INTO image_model_compatibility VALUES('image-1','model-1','tested_pass')")
   c.execute("INSERT INTO model_deployment_compatibility VALUES('model-1','rev-1','tested_pass')")
  r=self.call('POST',f'/semantic-workflow-versions/{vid}/publish',who='ADMIN',body={'confirm':True})
  self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['gpu_deployed'],False)
  self.assertEqual(self.call('PATCH',f'/semantic-workflow-versions/{vid}/draft',who='ADMIN',body={'graph':sample('text2img')}).status_code,409)
  with self.db.connect() as c:
   with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE workflow_versions SET graph_checksum=? WHERE id=?",('a'*64,vid))
   c.rollback()
  self.assertEqual(self.call('GET',f"/semantic-workflows/{x['id']}/versions",who='ADMIN').json()['active_version_id'],vid)
 def test_sql_immutability_snapshot(self):
  x=self.new();vid=x['version_id'];self.call('POST',f'/semantic-workflow-versions/{vid}/validate')
  self.call('POST',f'/semantic-workflow-versions/{vid}/compile-preview',body={'client_request_id':'snap','parameters':params('text2img')})
  with self.db.connect() as c:
   with self.assertRaises(sqlite3.IntegrityError):c.execute("DELETE FROM workflow_compilations WHERE owner_user_id='A'")
   c.rollback()
 def test_no_direct_gpu_job_api(self):
  routes=[route.path for route in self.app.routes]
  self.assertFalse(any('generation/jobs' in p for p in routes))
 def test_no_cross_user_request_key(self):
  a=self.new();b=self.new(who='B');
  for x,w in [(a,'A'),(b,'B')]:
   v=x['version_id'];self.call('POST',f'/semantic-workflow-versions/{v}/validate',who=w)
   r=self.call('POST',f'/semantic-workflow-versions/{v}/compile-preview',who=w,body={'client_request_id':'shared','parameters':params('text2img')})
   self.assertEqual(r.status_code,201,r.text)
  with self.db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM workflow_compilations').fetchone()[0],2)

if __name__=='__main__':unittest.main()
