"""Phase08 API security/seed/graph tests on synthetic A/B sessions and private SQLite."""
import os,json,sqlite3,unittest,importlib
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_phase07_registry import RegistryCase
from app.dynamic_params import MAX_SEED,compile_lora_graph,resolve,validate_schema,ParameterError
from app.migrations.phase08 import migrate as phase08

class ParamCase(unittest.TestCase):
 post=RegistryCase.post
 family=RegistryCase.family
 image=RegistryCase.image
 gpu=RegistryCase.gpu
 profile=RegistryCase.profile
 cfg=RegistryCase.cfg
 @classmethod
 def setUpClass(cls):
  RegistryCase.setUpClass.__func__(cls)
  import sys
  sys.modules.pop('app.registry_api',None);sys.modules.pop('app.parameters_api',None)
  cls.registry=importlib.import_module('app.registry_api')
 @classmethod
 def tearDownClass(cls):
  RegistryCase.tearDownClass.__func__(cls)
 def tearDown(self):
  RegistryCase.tearDown(self)
 def setUp(self):
  RegistryCase.setUp(self)
  os.environ['DYNAMIC_PARAMETERS_ENABLED']='true'
  self.parameters=importlib.import_module('app.parameters_api')
  full=FastAPI();full.include_router(self.registry.router);full.include_router(self.parameters.router)
  self.ad.close();self.normal.close()
  self.ad=TestClient(full,base_url='https://testserver');self.normal=TestClient(full,base_url='https://testserver')
  for c,raw in ((self.ad,self.rawA),(self.normal,self.rawB)):
   c.cookies.set(self.security.COOKIE_NAME,raw);c.headers['Origin']='https://testserver'
  with self.db.connect() as c:assert phase08(c);assert not phase08(c)
  self.family_id=self.family()
  self.model=self.post('/api/admin/models',{'family_id':self.family_id,'revision':'v1','license_id':'Apache-2.0','artifact_sha256':'a'*64,'precision':'fp8','vram_gb':24,'capabilities':{'image_edit':True}}).json()['id']
  self.lora=self.post('/api/admin/loras',{'family_id':self.family_id,'name':'LoRA','revision':'1','artifact_sha256':'b'*64,'logical_name':'approved.safetensors','size_bytes':1200,'min_strength':0,'max_strength':2,'trigger_words':['example']}).json()['id']
  self.image_id=self.image();self.gpu_id=self.gpu();self.prof=self.profile();self.rev_id=self.post('/api/admin/deployment-profiles/'+self.prof+'/revisions',{'image_id':self.image_id,'gpu_id':self.gpu_id,'config':self.cfg(),'env':{}}).json()['id']
  self.workflow='wf08';self.graph={'10':{'class_type':'CheckpointLoaderSimple','inputs':{'ckpt_name':'test.safetensors'}},
  '20':{'class_type':'CLIPLoader','inputs':{'clip_name':'clip.safetensors'}},
  '100':{'class_type':'Sampler','inputs':{'seed':'{{generation.seed}}','steps':'{{generation.steps}}','prompt':'{{prompt.positive}}','model':['110',0],'clip':['110',1]}},
  '110':{'class_type':'LoraLoader','inputs':{'model':['10',0],'clip':['20',0],'lora_name':'default.safetensors','strength_model':1,'strength_clip':1}}}
  with self.db.connect() as c:
   c.execute('INSERT INTO workflows(id,name,api_prompt,created_at) VALUES(?,?,?,?)',(self.workflow,'offline',json.dumps(self.graph),self.security.iso()))
   c.execute("UPDATE model_versions SET status='ready' WHERE id=?",(self.model,))
   c.execute("UPDATE worker_images SET signature_status='verified',status='approved' WHERE id=?",(self.image_id,))
   c.execute("UPDATE deployment_profile_revisions SET status='active' WHERE id=?",(self.rev_id,))
   c.execute('UPDATE deployment_profiles SET active_revision_id=? WHERE id=?',(self.rev_id,self.prof))
   c.execute('INSERT INTO image_model_compatibility VALUES(?,?,?,?,?)',(self.image_id,self.model,'tested_pass','SYNTHETIC ONLY',self.security.iso()))
   c.execute('INSERT INTO model_deployment_compatibility VALUES(?,?,?,?,?)',(self.model,self.rev_id,'tested_pass','SYNTHETIC ONLY',self.security.iso()))
  self.schema={'schema_version':'v1','fields':[
   {'key':'prompt','type':'text','required':True,'variable_key':'prompt.positive','label':'Prompt'},
   {'key':'steps','type':'integer','default':4,'min':1,'max':30,'step':1,'variable_key':'generation.steps'},
   {'key':'seed','type':'seed','required':True,'supports_random':True,'variable_key':'generation.seed'}],
   'lora_slots':{self.lora:'110'}}
  r=self.post('/api/admin/parameter-schemas',{'model_version_id':self.model,'workflow_id':self.workflow,'schema':self.schema})
  assert r.status_code==201,r.text
  self.schema_id=r.json()['id'];self.schema_hash=r.json()['schema_hash']
  r=self.post('/api/admin/parameter-schemas/'+self.schema_id+'/publish')
  assert r.status_code==200,r.text

 def intent(self,**extra):
  body={'client_request_id':'unique-01','model_version_id':self.model,'workflow_id':self.workflow,'schema_hash':self.schema_hash,
    'parameters':{'prompt':'hello'},'seed_mode':'random','batch_count':2,'batch_mode':'INCREMENT','loras':[]}
  body.update(extra)
  return self.post('/api/parameter-intents',body)
 def test_01_schema_public_and_admin_denied_to_b(self):
  self.assertEqual(self.normal.get(f'/api/models/{self.model}/parameter-schema?workflow_id={self.workflow}').status_code,200)
  self.assertEqual(self.normal.get('/api/admin/loras').status_code,403)
  self.assertEqual(self.normal.get('/api/presets').json()['items'],[])
 def test_02_unsupported_field_path_and_secrets(self):
  r=self.intent(parameters={'prompt':'hello','cfg':2});self.assertEqual(r.status_code,422,r.text)
  self.assertEqual(r.json()['detail']['field_path'],'parameters.cfg')
  self.assertEqual(self.intent(parameters={'prompt':'hello','api_key':'s'}).status_code,422)
 def test_03_random_seed_materialization_replay(self):
  a=self.intent();b=self.intent()
  self.assertEqual(a.status_code,201,a.text);self.assertTrue(b.json()['replayed'])
  self.assertEqual(a.json()['snapshot']['seeds_per_output'],b.json()['snapshot']['seeds_per_output'])
  self.assertFalse(a.json()['can_submit']);self.assertEqual(len(a.json()['snapshot']['seeds_per_output']),2)
  other=self.intent(client_request_id='unique-02').json()['snapshot']
  self.assertNotEqual(a.json()['snapshot']['effective']['seed'],other['effective']['seed'])
  self.assertEqual(self.intent(parameters={'prompt':'changed'}).status_code,409)
 def test_04_seed_max_u64_and_overflow(self):
  a=self.intent(seed_mode='fixed',parameters={'prompt':'hello','seed':str(MAX_SEED)},batch_count=1)
  self.assertEqual(a.status_code,201,a.text)
  self.assertEqual(a.json()['snapshot']['seeds_per_output'],[str(MAX_SEED)])
  self.assertEqual(self.intent(client_request_id='next',seed_mode='fixed',parameters={'prompt':'hello','seed':str(MAX_SEED)},batch_count=2).status_code,422)
  self.assertEqual(self.intent(client_request_id='bad',seed_mode='fixed',parameters={'prompt':'hello','seed':str(MAX_SEED+1)},batch_count=1).status_code,422)
 def test_05_owner_only_preset(self):
  p=self.post('/api/presets',{'name':'My setup','model_version_id':self.model,'workflow_id':self.workflow,'schema_hash':self.schema_hash,'values':{'steps':10}})
  self.assertEqual(p.status_code,201,p.text);pid=p.json()['id']
  self.assertEqual(self.normal.get('/api/presets/'+pid).status_code,404)
  self.assertEqual(self.normal.get('/api/presets').json()['items'],[])
  self.assertEqual(self.normal.get('/api/presets/'+pid+'/preview?model_version_id='+self.model+'&workflow_id='+self.workflow).status_code,404)
  self.assertEqual(self.normal.patch('/api/presets/'+pid,json={'name':'steal'},headers={'X-CSRF-Token':self.csrfB}).status_code,404)
  self.assertTrue(self.ad.get('/api/presets/'+pid+'/preview?model_version_id='+self.model+'&workflow_id='+self.workflow).json()['compatible'])
 def test_06_preset_credential_and_prompt_consent(self):
  for values in ({'R2_SECRET_KEY':'a'},{'prompt':'https://private.example.com/signed'},{'steps':100}):
   r=self.post('/api/presets',{'name':'My setup','model_version_id':self.model,'workflow_id':self.workflow,'schema_hash':self.schema_hash,'values':values})
   self.assertEqual(r.status_code,422,r.text)
  r=self.post('/api/presets',{'name':'My setup','model_version_id':self.model,'workflow_id':self.workflow,'schema_hash':self.schema_hash,'values':{'prompt':'hello'},'includes_prompt':True})
  self.assertEqual(r.status_code,201,r.text)
 def test_07_preset_lifecycle(self):
  p=self.post('/api/presets',{'name':'One','model_version_id':self.model,'workflow_id':self.workflow,'schema_hash':self.schema_hash,'values':{'steps':3}}).json()['id']
  self.assertEqual(self.ad.patch('/api/presets/'+p,json={'name':'Two'},headers={'X-CSRF-Token':self.csrfA}).status_code,200)
  self.assertEqual(self.ad.delete('/api/presets/'+p,headers={'X-CSRF-Token':self.csrfA}).status_code,204)
  self.assertEqual(self.ad.get('/api/presets/'+p).status_code,404)
 def test_08_lora_disabled_removed_from_graph(self):
  off={'id':self.lora,'version':'1','enabled':False,'model_strength':1.2,'clip_strength':0.8,'order':0}
  r=self.intent(loras=[off]);self.assertEqual(r.status_code,201,r.text)
  self.assertEqual(r.json()['snapshot']['effective_loras'],[])
  graph,active=compile_lora_graph(self.graph,{self.lora:'110'},[off],{self.lora:{'version':'1','verified':False,'logical_name':'approved.safetensors','min_strength':0,'max_strength':2}})
  self.assertNotIn('110',graph);self.assertEqual(graph['100']['inputs']['model'],['10',0]);self.assertEqual(graph['100']['inputs']['clip'],['20',0]);self.assertEqual(active,[])
 def test_09_lora_enabled_unverified_denied(self):
  selected={'id':self.lora,'version':'1','enabled':True,'model_strength':1,'clip_strength':1,'order':0}
  self.assertEqual(self.intent(loras=[selected]).status_code,422)
  self.assertEqual(self.normal.get(f'/api/models/{self.model}/loras').json()['items'],[])
 def test_10_synthetic_install_graph_enables_lora(self):
  with self.db.connect() as c:
   c.execute('INSERT INTO model_lora_compatibility VALUES(?,?,?,?,?)',(self.model,self.lora,'tested_pass','SYNTHETIC ONLY',self.security.iso()))
   c.execute('INSERT INTO lora_installations VALUES(?,?,?,?,?)',(self.image_id,self.lora,'verified','b'*64,self.security.iso()))
  items=self.normal.get(f'/api/models/{self.model}/loras').json()['items'];self.assertEqual(len(items),1)
  selected={'id':self.lora,'version':'1','enabled':True,'model_strength':1.5,'clip_strength':0.75,'order':0}
  r=self.intent(loras=[selected]);self.assertEqual(r.status_code,201,r.text)
  self.assertEqual(r.json()['snapshot']['effective_loras'][0]['model_strength'],1.5)
  graph,active=compile_lora_graph(self.graph,{self.lora:'110'},[selected],{self.lora:{'version':'1','verified':True,'logical_name':'approved.safetensors','min_strength':0,'max_strength':2}})
  self.assertEqual(graph['110']['inputs']['strength_clip'],0.75)
 def test_11_csrf_and_flag(self):
  self.assertEqual(self.ad.post('/api/parameter-intents',json={}).status_code,403)
  os.environ['DYNAMIC_PARAMETERS_ENABLED']='false'
  self.assertEqual(self.ad.get('/api/presets').status_code,503)
 def test_12_no_real_job_or_gpu(self):
  self.assertEqual(self.ad.post('/api/generation/jobs',headers={'X-CSRF-Token':self.csrfA}).status_code,503)
  with self.db.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],2)
 def test_13_intent_cross_user_404(self):
  id=self.intent().json()['id'];self.assertEqual(self.normal.get('/api/parameter-intents/'+id).status_code,404)
 def test_14_workflow_revision_not_silent(self):
  with self.db.connect() as c:c.execute('UPDATE workflows SET api_prompt=? WHERE id=?',(json.dumps({'new':{}}),self.workflow))
  self.assertEqual(self.intent().status_code,409)
 def test_15_malformed_bindings(self):
  r=self.post('/api/admin/parameter-schemas',{'model_version_id':self.model,'workflow_id':self.workflow,'schema':{'schema_version':'v2','fields':[{'key':'fake','type':'number','variable_key':'not.present'}]}})
  self.assertEqual(r.status_code,422,r.text)
 def test_17_no_selection_bypasses_preconfigured_lora(self):
  availability={}
  graph,active=compile_lora_graph(self.graph,{self.lora:'110'},[],availability)
  self.assertNotIn('110',graph)
  self.assertEqual(graph['100']['inputs']['model'],['10',0])
  self.assertEqual(self.intent().status_code,201)
 def test_18_preset_saves_disabled_lora_config(self):
  disabled={'id':self.lora,'version':'1','enabled':False,'model_strength':1.75,'clip_strength':0.35,'order':0}
  p=self.post('/api/presets',{'name':'Off state','model_version_id':self.model,'workflow_id':self.workflow,'schema_hash':self.schema_hash,'values':{'steps':4},'loras':[disabled]})
  self.assertEqual(p.status_code,201,p.text)
  d=self.ad.get('/api/presets/'+p.json()['id']).json()
  self.assertFalse(d['loras'][0]['enabled'])
  self.assertEqual(d['loras'][0]['model_strength'],1.75)
  self.assertEqual(self.normal.get('/api/presets/'+p.json()['id']).status_code,404)
 def test_19_model_seed_bounds_and_support(self):
  spec={'schema_version':'x','fields':[{'key':'seed','type':'seed','supports_random':True,'min':100,'max':101,'variable_key':'generation.seed'}]}
  self.assertEqual(resolve(spec,{},seed_mode='random',batch_count=2,batch_mode='INCREMENT',rng=lambda:100)['seeds_per_output'],['100','101'])
  with self.assertRaises(ParameterError):resolve(spec,{'seed':'101'},seed_mode='fixed',batch_count=2,batch_mode='INCREMENT')
  spec['fields'][0]['supports_random']=False
  with self.assertRaises(ParameterError):resolve(spec,{},seed_mode='random')
 def test_20_image_reference_sql_owner_checked_before_intent(self):
  graph=dict(self.graph)
  graph['150']={'class_type':'LoadImage','inputs':{'image':'{{input.image_1}}'}}
  with self.db.connect() as c:c.execute('UPDATE workflows SET api_prompt=? WHERE id=?',(json.dumps(graph),self.workflow))
  spec={'schema_version':'v2','fields':[
   {'key':'prompt','type':'text','required':True,'variable_key':'prompt.positive'},
   {'key':'steps','type':'integer','default':4,'min':1,'max':30,'variable_key':'generation.steps'},
   {'key':'seed','type':'seed','required':True,'supports_random':True,'variable_key':'generation.seed'},
   {'key':'reference','type':'image','required':True,'variable_key':'input.image_1'}],
   'lora_slots':{self.lora:'110'}}
  r=self.post('/api/admin/parameter-schemas',{'model_version_id':self.model,'workflow_id':self.workflow,'schema':spec})
  self.assertEqual(r.status_code,201,r.text);schema_hash=r.json()['schema_hash'];self.assertEqual(self.post('/api/admin/parameter-schemas/'+r.json()['id']+'/publish').status_code,200)
  bad=self.intent(schema_hash=schema_hash,parameters={'prompt':'hi','reference':'B-output'})
  self.assertEqual(bad.status_code,404,bad.text)
  good=self.intent(schema_hash=schema_hash,parameters={'prompt':'hi','reference':'A-output'})
  self.assertEqual(good.status_code,201,good.text)
  self.assertFalse(good.json()['can_submit'])
 def test_16_seed_step_validation(self):
  r=self.intent(parameters={'prompt':'hi','steps':40});self.assertEqual(r.status_code,422)
  with self.assertRaises(ParameterError):validate_schema({'schema_version':'a','fields':[{'key':'x','type':'integer','step':0,'variable_key':'generation.steps'}]})

if __name__=='__main__':unittest.main()
