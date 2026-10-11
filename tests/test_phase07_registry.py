"""Two-user HTTP/SQLite safety checks; uses Phase06 TEST fixture and no GPU/network."""
import os,sqlite3,unittest,importlib
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_phase06_media import MediaCase
from app.migrations.phase05 import migrate as m05
from app.migrations.phase07 import migrate as m07

class RegistryCase(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  MediaCase.setUpClass.__func__(cls);cls.registry=importlib.import_module('app.registry_api')
 @classmethod
 def tearDownClass(cls):MediaCase.tearDownClass.__func__(cls)
 def setUp(self):
  MediaCase.setUp(self)
  with self.db.connect() as c:
   assert m05(c);assert m07(c);assert not m07(c)
   c.execute('INSERT INTO user_roles(user_id,role_id,granted_at) VALUES(?,?,?)',('A','admin',self.security.iso()))
  os.environ['MODEL_REGISTRY_ENABLED']='true'
  os.environ['MODEL_REGISTRY_TRUSTED_REPOS']='ghcr.io/example/worker'
  app=FastAPI();app.include_router(self.registry.router)
  self.ad=TestClient(app,base_url='https://testserver');self.normal=TestClient(app,base_url='https://testserver')
  for client,raw in ((self.ad,self.rawA),(self.normal,self.rawB)):
   client.cookies.set(self.security.COOKIE_NAME,raw);client.headers['Origin']='https://testserver'
 def tearDown(self):self.ad.close();self.normal.close();MediaCase.tearDown(self)
 def post(self,url,data={},client=None,csrf=True):
  client=client or self.ad;headers={'X-CSRF-Token':self.csrfA} if csrf else {}
  return client.post(url,json=data,headers=headers)
 def family(self):
  r=self.post('/api/admin/models/families',{'name':'Qwen','vendor':'Test','modality':'image'})
  self.assertEqual(r.status_code,201,r.text);return r.json()['id']
 def image(self):
  r=self.post('/api/admin/worker-images',{'name':'worker','repo':'ghcr.io/example/worker','tag':'stable','digest':'sha256:'+'f'*64,'nodes':['KSampler']})
  self.assertEqual(r.status_code,201,r.text);return r.json()['id']
 def gpu(self):
  r=self.post('/api/admin/gpu-profiles',{'name':'5090','gpu_family':'RTX5090','provider':'salad','vram_gb':32,'ram_gb':32,'cpu_count':4,'disk_gb':100,'shm_mb':2048})
  self.assertEqual(r.status_code,201,r.text);return r.json()['id']
 def profile(self):
  r=self.post('/api/admin/deployment-profiles',{'name':'default'})
  self.assertEqual(r.status_code,201,r.text);return r.json()['id']
 def cfg(self):return {'min_replicas':0,'max_replicas':1,'idle_timeout_seconds':600,'startup_timeout_seconds':300,'readiness_path':'/ready','health_path':'/health'}
 def rev(self,env=None):
  p=self.profile();i=self.image();g=self.gpu()
  r=self.post('/api/admin/deployment-profiles/'+p+'/revisions',{'image_id':i,'gpu_id':g,'config':self.cfg(),'env':env or {}})
  return p,r
 def test_01_user_denied_admin_even_internal_token(self):
  self.assertEqual(self.normal.get('/api/admin/worker-images',headers={'X-Internal-Token':'xyz'}).status_code,403)
  self.assertEqual(self.normal.get('/api/catalog/models').status_code,200)
 def test_02_flag_default_off(self):
  os.environ['MODEL_REGISTRY_ENABLED']='false';self.assertEqual(self.ad.get('/api/admin/models').status_code,503)
 def test_03_ready_model_without_runtime_not_public(self):
  f=self.family();r=self.post('/api/admin/models',{'family_id':f,'revision':'v1','license_id':'Apache-2.0','artifact_sha256':'d'*64,'precision':'fp8','vram_gb':24,'capabilities':{'image_edit':True}})
  self.assertEqual(r.status_code,201,r.text)
  with self.db.connect() as c:c.execute("UPDATE model_versions SET status='ready' WHERE id=?",(r.json()['id'],))
  self.assertEqual(self.normal.get('/api/catalog/models').json()['items'],[])
 def test_04_image_digest_pinned_no_external(self):
  wrong={'name':'worker','repo':'docker.io/evil/worker','tag':'latest','digest':'sha256:'+'a'*64}
  self.assertEqual(self.post('/api/admin/worker-images',wrong).status_code,422)
  wrong['repo']='ghcr.io/example/worker';wrong['digest']='latest'
  self.assertEqual(self.post('/api/admin/worker-images',wrong).status_code,422)
 def test_05_duplicate_image_and_immutable_digest(self):
  i=self.image()
  with self.db.connect() as c:
   with self.assertRaises(sqlite3.IntegrityError):c.execute('UPDATE worker_images SET digest=? WHERE id=?',('sha256:'+'a'*64,i))
  self.assertEqual(self.post('/api/admin/worker-images',{'name':'duplicate','repo':'ghcr.io/example/worker','tag':'v2','digest':'sha256:'+'f'*64}).status_code,409)
 def test_06_revision_and_secret_masked(self):
  p,r=self.rev({'R2_ACCESS_KEY_REF':'vault://staging/r2-key','WORKER_CONCURRENCY':2})
  self.assertEqual(r.status_code,201,r.text)
  h=self.ad.get('/api/admin/deployment-profiles/'+p+'/history').json()
  self.assertEqual(h['items'][0]['env']['R2_ACCESS_KEY_REF'],'[configured]')
  self.assertNotIn('r2-key',str(h))
 def test_07_bad_env_rejected(self):
  p,i,g=self.profile(),self.image(),self.gpu()
  for env in ({'R2_ACCESS_KEY_REF':'plaintext-password'},{'SHELL_COMMAND':'echo bad'},{'WORKER_CONCURRENCY':'high'}):
   r=self.post('/api/admin/deployment-profiles/'+p+'/revisions',{'image_id':i,'gpu_id':g,'config':self.cfg(),'env':env})
   self.assertEqual(r.status_code,422,r.text)
 def test_08_validate_never_activates(self):
  p,r=self.rev();self.assertEqual(r.status_code,201,r.text)
  rid=r.json()['id'];v=self.post(f'/api/admin/deployment-profiles/{p}/validate?revision_id={rid}')
  self.assertEqual(v.status_code,200,v.text);self.assertFalse(v.json()['safe_to_activate'])
  self.assertIsNone(self.ad.get('/api/admin/deployment-profiles').json()['items'][0]['active_revision_id'])
 def test_09_activation_approval_rollback_blocked(self):
  p,r=self.rev();rid=r.json()['id']
  for action in ('approve','activate','rollback'):
   self.assertEqual(self.post(f'/api/admin/deployment-profiles/{p}/{action}?revision_id={rid}').status_code,503)
 def test_10_csrf_and_origin(self):
  self.assertEqual(self.post('/api/admin/models/families',{'name':'A','vendor':'B','modality':'image'},csrf=False).status_code,403)
  self.assertEqual(self.ad.post('/api/admin/models/families',json={'name':'A','vendor':'B','modality':'image'},headers={'Origin':'https://evil.invalid','X-CSRF-Token':self.csrfA}).status_code,403)
 def test_11_revision_and_audit_immutable(self):
  p,r=self.rev();rid=r.json()['id']
  with self.db.connect() as c:
   with self.assertRaises(sqlite3.IntegrityError):c.execute('UPDATE deployment_profile_revisions SET env_json=? WHERE id=?',('{}',rid))
   with self.assertRaises(sqlite3.IntegrityError):c.execute('DELETE FROM registry_audit')
 def test_12_no_secrets_in_user_catalog(self):
  self.family();obj=str(self.normal.get('/api/catalog/models').json())
  for forbidden in ('repo','digest','vault','env_json','artifact_sha256'):self.assertNotIn(forbidden,obj)


 def test_13_untrusted_ghcr_is_forbidden(self):
  body={'name':'evil','repo':'ghcr.io/someone/worker','tag':'v1','digest':'sha256:'+'a'*64}
  self.assertEqual(self.post('/api/admin/worker-images',body).status_code,403)
  os.environ['MODEL_REGISTRY_TRUSTED_REPOS']=''
  self.assertEqual(self.post('/api/admin/worker-images',body).status_code,503)
 def test_14_synthetic_verified_pair_does_not_leak_internals(self):
  f=self.family()
  m=self.post('/api/admin/models',{'family_id':f,'revision':'v1','license_id':'Apache-2.0',
    'artifact_sha256':'d'*64,'precision':'fp8','vram_gb':24,'capabilities':{'image_edit':True}}).json()['id']
  i=self.image();g=self.gpu();p=self.profile()
  rid=self.post('/api/admin/deployment-profiles/'+p+'/revisions',{'image_id':i,'gpu_id':g,'config':self.cfg(),'env':{}}).json()['id']
  with self.db.connect() as c:
   c.execute("UPDATE model_versions SET status='ready' WHERE id=?",(m,))
   c.execute("UPDATE worker_images SET status='approved',signature_status='verified' WHERE id=?",(i,))
   c.execute("UPDATE deployment_profile_revisions SET status='active' WHERE id=?",(rid,))
   c.execute('UPDATE deployment_profiles SET active_revision_id=? WHERE id=?',(rid,p))
   c.execute('INSERT INTO image_model_compatibility VALUES(?,?,?,?,?)',(i,m,'tested_pass','synthetic-only','2026-01-01T00:00:00+00:00'))
   c.execute('INSERT INTO model_deployment_compatibility VALUES(?,?,?,?,?)',(m,rid,'tested_pass','synthetic-only','2026-01-01T00:00:00+00:00'))
  items=self.normal.get('/api/catalog/models').json()['items']
  self.assertEqual(len(items),1)
  self.assertEqual(items[0]['readiness'],'unknown')
  self.assertNotIn('digest',str(items));self.assertNotIn('vault://',str(items))

if __name__=='__main__':unittest.main()
