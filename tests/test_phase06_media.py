"""Phase06 live HTTP A/B security rehearsal over disposable SQLite and fake private R2.

Uses original Phase01/02 migrations and Phase02 session/CSRF implementation from
checked GitHub package; replaces only unavailable production db/config/storage adapters.
"""
from __future__ import annotations
import os,sqlite3,sys,tempfile,types,io,unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
LEGACY='''
CREATE TABLE workflows(id TEXT PRIMARY KEY,name TEXT,api_prompt TEXT,created_at TEXT,updated_at TEXT);
CREATE TABLE jobs(id TEXT PRIMARY KEY,workflow_id TEXT,client_request_id TEXT,request_hash TEXT,
 request_json TEXT NOT NULL,variables_json TEXT,snapshot_json TEXT,state TEXT NOT NULL,
 hidden INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 execution_mode TEXT NOT NULL DEFAULT 'direct',active_attempt_id TEXT,
 FOREIGN KEY(workflow_id) REFERENCES workflows(id));
CREATE UNIQUE INDEX idx_jobs_client_request ON jobs(client_request_id) WHERE client_request_id IS NOT NULL;
CREATE TABLE input_assets(asset_id TEXT PRIMARY KEY,storage_key TEXT NOT NULL UNIQUE,
 mime_type TEXT NOT NULL,size_bytes INTEGER,width INTEGER,height INTEGER,created_at TEXT NOT NULL);
CREATE TABLE job_assets(asset_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,attempt_id TEXT,
 storage_key TEXT NOT NULL,media_type TEXT,mime_type TEXT,status TEXT NOT NULL,
 width INTEGER,height INTEGER,size_bytes INTEGER,created_at TEXT NOT NULL);
'''

from app.migrations.phase01 import migrate as phase01
from app.migrations.phase02 import migrate as phase02
from app.migrations.phase06 import migrate as phase06

class BlobBody:
 def __init__(self,value):self.value=value
 def iter_chunks(self,chunk_size=262144):yield self.value
 def close(self):pass

class MediaCase(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  # Tests are isolated in a synthetic package. No real network or database.
  cls.saved={k:sys.modules.get(k) for k in ('app.db','app.storage','app.config')}
  cls.db=types.ModuleType('app.db');cls.storage=types.ModuleType('app.storage');cls.config=types.ModuleType('app.config')
  cls.config.settings=types.SimpleNamespace(max_upload_mb=3,r2_presign_ttl_seconds=60,r2_bucket='test-only')
  sys.modules['app.db']=cls.db;sys.modules['app.storage']=cls.storage;sys.modules['app.config']=cls.config
  import app,importlib
  app.db=cls.db;app.storage=cls.storage
  for name in ('app.security','app.owner_repository','app.media_repository','app.media_api'):
   if name in sys.modules:del sys.modules[name]
  cls.security=importlib.import_module('app.security')
  cls.api=importlib.import_module('app.media_api')
  cls.owner_api=importlib.import_module('app.owner_api')
  cls.repo=importlib.import_module('app.media_repository')
 @classmethod
 def tearDownClass(cls):
  for k,v in cls.saved.items():
   if v is None:sys.modules.pop(k,None)
   else:sys.modules[k]=v

 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'isolated-copy.db'
  with sqlite3.connect(self.path) as c:
   c.executescript(LEGACY);c.commit();phase01(c);phase02(c);self.assertTrue(phase06(c));self.assertFalse(phase06(c))
  @contextmanager
  def connect():
   c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
   try:
    with c:yield c
   finally:c.close()
  self.db.connect=connect;self.db.utcnow=lambda:self.security.iso()
  self.env=patch.dict(os.environ,{'AUTH_ENABLED':'true','AUTH_PUBLIC_ORIGIN':'https://testserver',
   'AUTH_CSRF_SECRET':'Q'*48,'AUTH_IDLE_SECONDS':'3600','MEDIA_LIBRARY_ENABLED':'true','OWNER_ISOLATION_ENABLED':'true'});self.env.start()
  self.objects={}
  def upload(obj,key,mime=None):self.objects[key]=obj.read();return key
  def get(key):
   if key not in self.objects:raise FileNotFoundError()
   val=self.objects[key];return {'Body':BlobBody(val),'ContentLength':len(val)}
  self.storage.upload_fileobj=upload;self.storage.get_object=get
  class Head:
   def head_object(_,Bucket,Key):
    val=self.objects[Key]
    return {'ContentLength':len(val),'ContentType':'image/webp' if Key.endswith('.webp') else 'image/png'}
  self.storage.client=lambda:Head()
  self.storage.presign_get=lambda key,ttl=None:'https://signed.test.invalid/opaque-ticket'
  with self.db.connect() as c:
   c.execute('BEGIN IMMEDIATE')
   for uid in ('A','B'):
    now=self.security.iso()
    c.execute('''INSERT INTO users(id,email,email_normalized,password_hash,display_name,status,email_verified_at,
      created_at,updated_at) VALUES(?,?,?,?,?,'active',?,?,?)''',
      (uid,uid.lower()+'@example.com',uid.lower()+'@example.com','argon2-hash-test',uid,now,now,now))
    c.execute('INSERT INTO user_roles(user_id,role_id,granted_at) VALUES(?,?,?)',(uid,'user',now))
    _,raw,_=self.security.create_session(c,uid,False)
    setattr(self,'raw'+uid,raw)
    c.execute('''INSERT INTO jobs(id,request_json,variables_json,state,created_at,updated_at,owner_user_id,ownership_state)
      VALUES(?,?,?,?,?,?,?,'verified')''',(uid+'-job','{}','{}','succeeded',now,now,uid))
    c.execute('''INSERT INTO job_assets(asset_id,job_id,storage_key,mime_type,media_type,status,created_at,owner_user_id,ownership_state)
      VALUES(?,?,?,?,?,'available',?,?,'verified')''',
      (uid+'-output',uid+'-job','outputs/'+uid+'-job/image.png','image/png','image',now,uid))
    self.objects['outputs/'+uid+'-job/image.png']=b'output bytes '+uid.encode()
  app=FastAPI();app.include_router(self.api.router);app.include_router(self.owner_api.router)
  self.a=TestClient(app,base_url='https://testserver');self.b=TestClient(app,base_url='https://testserver')
  for client,raw in ((self.a,self.rawA),(self.b,self.rawB)):
   client.cookies.set(self.security.COOKIE_NAME,raw);client.headers['Origin']='https://testserver'
  self.csrfA=self.security.csrf_for_session(self.rawA)
  self.csrfB=self.security.csrf_for_session(self.rawB)

 def tearDown(self):self.a.close();self.b.close();self.env.stop();self.tmp.cleanup()
 def call(self,client,method,path,csrf=None,**kw):
  h=kw.pop('headers',{})
  if csrf:h['X-CSRF-Token']=csrf
  return getattr(client,method)(path,headers=h,**kw)
 def test_01_cross_user_idor_details(self):
  self.assertEqual(self.a.get('/api/assets/B-output').status_code,404)
  self.assertEqual(self.b.get('/api/assets/A-output').status_code,404)
  self.assertEqual(self.a.get('/api/assets/A-output').json()['job_id'],'A-job')
 def test_02_preview_original_private(self):
  self.assertEqual(self.a.get('/api/assets/A-output/preview').content,b'output bytes A')
  self.assertEqual(self.b.get('/api/assets/A-output/preview').status_code,404)
  self.assertIn('no-store',self.a.get('/api/assets/A-output/preview').headers['cache-control'])
 def test_03_download_and_ticket_owner_only(self):
  self.assertEqual(self.a.get('/api/assets/A-output/download').content,b'output bytes A')
  self.assertEqual(self.b.get('/api/assets/A-output/download').status_code,404)
  self.assertEqual(self.call(self.b,'post','/api/assets/A-output/download-ticket',self.csrfB).status_code,404)
  self.assertEqual(self.call(self.a,'post','/api/assets/A-output/download-ticket',self.csrfA).json()['expires_in'],60)
 def test_04_list_and_cursor_isolation(self):
  res=self.a.get('/api/assets?limit=1');self.assertEqual(res.status_code,200,res.text)
  self.assertNotIn('B-output',res.text);self.assertNotIn('storage_key',res.text)
  with self.db.connect() as c:
   now=self.security.iso()
   c.execute('INSERT INTO input_assets(asset_id,storage_key,mime_type,created_at,owner_user_id,ownership_state) VALUES(?,?,?,?,?,?)',
    ('A-input','inputs/A-input/original.png','image/png',now,'A','verified'))
  page=self.a.get('/api/assets?limit=1').json()
  self.assertIsNotNone(page['next_cursor'])
  self.assertEqual(self.b.get('/api/assets?limit=1&cursor='+page['next_cursor']).status_code,422)
  self.assertEqual(self.a.get('/api/assets?limit=1&type=video&cursor='+page['next_cursor']).status_code,422)
 def test_05_reuse_no_cross_user_and_no_job_created(self):
  path='/api/assets/A-output/reuse?role=pose&slot=input.image_2'
  self.assertEqual(self.call(self.b,'post',path,self.csrfB).status_code,404)
  r=self.call(self.a,'post',path,self.csrfA)
  self.assertEqual(r.status_code,200,r.text);self.assertFalse(r.json()['can_submit'])
  self.assertEqual(r.json()['source_job_id'],'A-job')
  with self.db.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM job_input_assets').fetchone()[0],0)
 def test_06_csrf_and_policy_gate(self):
  self.assertEqual(self.call(self.a,'post','/api/assets/A-output/reuse').status_code,403)
  with patch.dict(os.environ,{'MEDIA_LIBRARY_ENABLED':'false'}):
   self.assertEqual(self.a.get('/api/assets').status_code,503)
 def test_07_delete_hides_only_selected_no_r2_delete(self):
  self.assertEqual(self.call(self.b,'delete','/api/assets/A-output',self.csrfB).status_code,404)
  self.assertEqual(self.call(self.a,'delete','/api/assets/A-output',self.csrfA).status_code,204)
  self.assertEqual(self.a.get('/api/assets/A-output').status_code,404)
  self.assertIn('outputs/A-job/image.png',self.objects)
  self.assertEqual(self.b.get('/api/assets/B-output').status_code,200)
  self.assertEqual(self.call(self.a,'post','/api/assets/A-output/use-as-input',self.csrfA).status_code,404)
  self.assertNotIn('A-output',self.a.get('/api/jobs/A-job/images').text)
 def test_08_immutable_reference_and_referenced_delete_conflict(self):
  with self.db.connect() as c:
   c.execute('BEGIN IMMEDIATE')
   now=self.security.iso()
   c.execute('INSERT INTO job_input_assets(job_id,slot_key,position,asset_id,owner_user_id,role,source_job_id,bound_at) VALUES(?,?,?,?,?,?,?,?)',
    ('A-job','input.image_1',0,'A-output','A','reference','A-job',now))
   c.commit()
   with self.assertRaises(sqlite3.IntegrityError):
    c.execute('UPDATE job_input_assets SET role=? WHERE job_id=?',('pose','A-job'))
   c.rollback()
  self.assertEqual(self.call(self.a,'delete','/api/assets/A-output',self.csrfA).status_code,409)
 def test_09_bad_reference_foreign_rejected_by_trigger(self):
  with self.db.connect() as c:
   with self.assertRaises(sqlite3.IntegrityError):
    c.execute('INSERT INTO job_input_assets(job_id,slot_key,position,asset_id,owner_user_id,role,bound_at) VALUES(?,?,?,?,?,?,?)',
     ('A-job','input.image_2',0,'B-output','A','pose',self.security.iso()))
 def test_10_source_job_lineage_must_match_asset(self):
  with self.db.connect() as c:
   with self.assertRaises(sqlite3.IntegrityError):
    c.execute('INSERT INTO job_input_assets(job_id,slot_key,position,asset_id,owner_user_id,role,source_job_id,bound_at) VALUES(?,?,?,?,?,?,?,?)',
     ('A-job','input.image_3',0,'A-output','A','reference','B-job',self.security.iso()))

 def test_10_upload_validation_and_private_thumb(self):
  bad=self.call(self.a,'post','/api/uploads',self.csrfA,files={'file':('malformed.png',b'not an image','image/png')})
  self.assertEqual(bad.status_code,422,bad.text)
  im=Image.new('RGB',(180,110),'red');buf=io.BytesIO();im.save(buf,format='PNG')
  fake=self.call(self.a,'post','/api/uploads',self.csrfA,files={'file':('fake.jpeg',buf.getvalue(),'image/jpeg')})
  self.assertEqual(fake.status_code,422)
  result=self.call(self.a,'post','/api/uploads',self.csrfA,files={'file':('image.png',buf.getvalue(),'image/png')})
  self.assertEqual(result.status_code,201,result.text)
  aid=result.json()['asset_id']
  self.assertEqual(self.b.get('/api/assets/'+aid+'/thumbnail').status_code,404)
  r=self.a.get('/api/assets/'+aid+'/thumbnail');self.assertEqual(r.status_code,200)
  self.assertTrue(r.content.startswith(b'RIFF'))
  self.assertEqual(self.a.get('/api/assets/'+aid+'/preview').content,buf.getvalue())
 def test_11_variant_owner_trigger_blocks_cross_user(self):
  with self.db.connect() as c:
   with self.assertRaises(sqlite3.IntegrityError):
    c.execute('INSERT INTO asset_variants(id,asset_id,owner_user_id,kind,storage_key,mime_type,size_bytes,verified_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
      ('forged','A-output','B','thumbnail','thumbnails/forged.webp','image/webp',8,self.security.iso(),self.security.iso()))

 def test_11_missing_thumbnail_does_not_fallback_large_original(self):
  self.assertEqual(self.a.get('/api/assets/A-output/thumbnail').status_code,404)
  self.assertEqual(self.b.get('/api/assets/A-output/thumbnail').status_code,404)
 def test_12_owner_session_revocation(self):
  with self.db.connect() as c:c.execute('UPDATE sessions SET revoked_at=? WHERE user_id=?',(self.security.iso(),'A'))
  self.assertEqual(self.a.get('/api/assets/A-output').status_code,401)
 def test_13_oversize_upload_and_head_integrity_gate(self):
  r=self.call(self.a,'post','/api/uploads',self.csrfA,files={'file':('large.png',b'X'*(3*1024*1024+5),'image/png')})
  self.assertEqual(r.status_code,413)
  old=self.storage.client
  class BadHead:
   def head_object(_,**kwargs):return {'ContentLength':0,'ContentType':'image/png'}
  self.storage.client=lambda:BadHead()
  im=Image.new('RGB',(2,2),'red');v=io.BytesIO();im.save(v,format='PNG')
  try:
   result=self.call(self.a,'post','/api/uploads',self.csrfA,files={'file':('x.png',v.getvalue(),'image/png')})
   self.assertEqual(result.status_code,503)
   with self.db.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM input_assets').fetchone()[0],0)
  finally:self.storage.client=old

 def test_14_feature_references_closed(self):
  self.assertEqual(self.call(self.a,'post','/api/jobs/A-job/references',self.csrfA).status_code,503)
  self.assertEqual(self.call(self.b,'post','/api/jobs/A-job/references',self.csrfB).status_code,404)

if __name__=='__main__':unittest.main()
