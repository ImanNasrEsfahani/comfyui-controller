"""Actual HTTP + SQLite isolation tests on mock session/CSRF (no GPU, no public deployment)."""
import os,sys,json,sqlite3
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_phase09_api import APITest
from backend.app.migrations import phase10

class StudioTest(APITest):
 def setUp(self):
  sys.modules.pop('backend.app.studio_api',None)
  super().setUp()
  with self.db.connect() as c:assert phase10.migrate(c)
  self.oldstudio=os.environ.get('WORKFLOW_STUDIO_ENABLED');os.environ['WORKFLOW_STUDIO_ENABLED']='true'
  self.oldpower=os.environ.get('WORKFLOW_STUDIO_POWER_USERS_ENABLED')
 def tearDown(self):
  if self.oldstudio is None:os.environ.pop('WORKFLOW_STUDIO_ENABLED',None)
  else:os.environ['WORKFLOW_STUDIO_ENABLED']=self.oldstudio
  if self.oldpower is None:os.environ.pop('WORKFLOW_STUDIO_POWER_USERS_ENABLED',None)
  else:os.environ['WORKFLOW_STUDIO_POWER_USERS_ENABLED']=self.oldpower
  super().tearDown()
  sys.modules.pop('backend.app.studio_api',None)
 def studio(self,method,path,who='ADMIN',body=None,csrf=True):
  return self.call(method,'/studio'+path,who=who,body=body,csrf=csrf)
 def system(self,kind='text2img'):
  return self.new('system','ADMIN',kind)
 def test_catalog_closed_to_normal_accounts(self):
  self.assertEqual(self.studio('GET','/nodes',who='A').status_code,403)
  r=self.studio('GET','/nodes');self.assertEqual(r.status_code,200,r.text)
  self.assertFalse(r.json()['worker_inventory_verified'])
  self.assertNotIn('PythonExec',str(r.json()))
 def test_stage10_feature_gate(self):
  os.environ['WORKFLOW_STUDIO_ENABLED']='false'
  self.assertEqual(self.studio('GET','/nodes').status_code,503)
 def test_save_reload_revision_and_stale_conflict(self):
  x=self.system();vid=x['version_id'];url=f'/versions/{vid}/editor'
  r=self.studio('GET',url);self.assertEqual(r.status_code,200,r.text)
  data=r.json();self.assertEqual(data['revision'],0);self.assertTrue(data['editable'])
  graph=data['graph']
  body={'revision':0,'graph':graph,'layout':{'model':{'x':100,'y':20}} if any(n['id']=='model' for n in graph['nodes']) else {},'viewport':{'x':0,'y':20,'zoom':1}}
  r=self.studio('PATCH',f'/versions/{vid}/draft',body=body);self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()['revision'],1)
  self.assertEqual(self.studio('GET',url).json()['revision'],1)
  rejected=self.studio('PATCH',f'/versions/{vid}/draft',body=body)
  self.assertEqual(rejected.status_code,409,rejected.text)
  self.assertEqual(rejected.json()['detail']['code'],'stale_revision')
 def test_invalid_cross_type_edge_rejected_without_draft_write(self):
  x=self.system();vid=x['version_id'];g=self.studio('GET',f'/versions/{vid}/editor').json()['graph']
  # Unsafe executable semantic node must never pass.
  g['nodes'][0]['kind']='PythonExec'
  r=self.studio('PATCH',f'/versions/{vid}/draft',body={'revision':0,'graph':g})
  self.assertEqual(r.status_code,422,r.text)
  with self.db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM studio_drafts').fetchone()[0],0)
 def test_incomplete_draft_can_save_but_not_validate(self):
  x=self.system();vid=x['version_id'];g=self.studio('GET',f'/versions/{vid}/editor').json()['graph']
  g['edges']=[]
  r=self.studio('PATCH',f'/versions/{vid}/draft',body={'revision':0,'graph':g});self.assertEqual(r.status_code,200,r.text)
  bad=self.studio('POST',f'/versions/{vid}/validate',body={'revision':1})
  self.assertEqual(bad.status_code,422,bad.text)
  self.assertEqual(self.studio('GET',f'/versions/{vid}/editor').json()['revision'],1)
 def test_validated_revision_and_existing_semantic_snapshot(self):
  x=self.system();vid=x['version_id'];g=self.studio('GET',f'/versions/{vid}/editor').json()['graph']
  self.assertEqual(self.studio('PATCH',f'/versions/{vid}/draft',body={'revision':0,'graph':g}).status_code,200)
  val=self.studio('POST',f'/versions/{vid}/validate',body={'revision':1})
  self.assertEqual(val.status_code,200,val.text);self.assertFalse(val.json()['runtime_verified'])
  with self.db.connect() as c:
   row=c.execute('SELECT graph_checksum,status FROM workflow_versions WHERE id=?',(vid,)).fetchone()
   self.assertEqual(row['status'],'validated');self.assertEqual(row['graph_checksum'],val.json()['checksum'])
 def test_owner_and_csrf(self):
  x=self.new(who='A');vid=x['version_id']
  self.assertEqual(self.studio('GET',f'/versions/{vid}/editor',who='B').status_code,403)
  self.assertEqual(self.studio('PATCH',f'/versions/{vid}/draft',csrf=False,body={'revision':0,'graph':{}},who='ADMIN').status_code,403)
 def test_restore_creates_new_version_without_modifying_old(self):
  x=self.system();vid=x['version_id'];u=f'/versions/{vid}'
  r=self.studio('POST',u+'/restore',body={'source_version_id':vid})
  self.assertEqual(r.status_code,201,r.text)
  with self.db.connect() as c:
   original=c.execute('SELECT graph_checksum FROM workflow_versions WHERE id=?',(vid,)).fetchone()[0]
   new=c.execute('SELECT graph_checksum,version FROM workflow_versions WHERE id=?',(r.json()['version_id'],)).fetchone()
   self.assertEqual(original,new[0]);self.assertEqual(new[1],2)
 def test_structural_preview_never_exposes_prompt_asset_or_signed_url(self):
  x=self.system();vid=x['version_id']
  self.assertEqual(self.studio('GET',f'/versions/{vid}/compile-preview').status_code,409)
  self.assertEqual(self.studio('POST',f'/versions/{vid}/validate',body={'revision':0}).status_code,200)
  r=self.studio('GET',f'/versions/{vid}/compile-preview')
  self.assertEqual(r.status_code,200,r.text)
  self.assertFalse(r.json()['dispatch_allowed'])
  self.assertNotIn('graph_json',r.text)
  self.assertNotIn('s3://',r.text)
  self.assertNotIn('https://',r.text)
 def test_publish_blocked_without_runtime_verification(self):
  x=self.system();vid=x['version_id'];self.studio('POST',f'/versions/{vid}/validate',body={'revision':0})
  r=self.studio('POST',f'/versions/{vid}/publish',body={'confirm':True})
  self.assertEqual(r.status_code,503,r.text)
 def test_no_unpublish_without_policy(self):
  x=self.system();r=self.studio('POST',f"/workflows/{x['id']}/unpublish",body={'confirm':True})
  self.assertEqual(r.status_code,503)
 def test_cross_owner_private_draft_inaccessible_even_to_admin(self):
  x=self.new(who='A');vid=x['version_id']
  self.assertEqual(self.studio('GET',f'/versions/{vid}/editor',who='ADMIN').status_code,404)
 def test_malformed_edge_value_is_rejected_not_server_error(self):
  x=self.system();vid=x['version_id'];g=self.studio('GET',f'/versions/{vid}/editor').json()['graph']
  g['edges'].append({'from':['unexpected'],'out':'any','to':'any','in':'any'})
  r=self.studio('PATCH',f'/versions/{vid}/draft',body={'revision':0,'graph':g})
  self.assertEqual(r.status_code,422,r.text)
 def test_submitted_layout_and_viewport_scope_are_strict(self):
  x=self.system();v=x['version_id'];g=self.studio('GET',f'/versions/{v}/editor').json()['graph']
  r=self.studio('PATCH',f'/versions/{v}/draft',body={'revision':0,'graph':g,'viewport':{'x':0,'y':0,'zoom':9000}})
  self.assertEqual(r.status_code,422,r.text)
 def test_unsafe_legacy_route_does_not_publish_editor_draft(self):
  x=self.system();v=x['version_id'];g=self.studio('GET',f'/versions/{v}/editor').json()['graph']
  g['edges']=[];self.assertEqual(self.studio('PATCH',f'/versions/{v}/draft',body={'revision':0,'graph':g}).status_code,200)
  self.assertEqual(self.studio('POST',f'/versions/{v}/validate',body={'revision':1}).status_code,422)
  with self.db.connect() as c:self.assertEqual(c.execute('SELECT status FROM workflow_versions WHERE id=?',(v,)).fetchone()[0],'draft')
 def test_layout_injection_refused(self):
  x=self.system();v=x['version_id'];g=self.studio('GET',f'/versions/{v}/editor').json()['graph']
  body={'revision':0,'graph':g,'layout':{'made-up-node':{'x':0,'y':0}}}
  self.assertEqual(self.studio('PATCH',f'/versions/{v}/draft',body=body).status_code,422)

if __name__=='__main__':
 import unittest;unittest.main()
