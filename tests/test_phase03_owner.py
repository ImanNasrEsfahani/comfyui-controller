"""A/B HTTP IDOR and SQL isolation rehearsal against Phase01/02 SQLite COPY."""
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
FAKE_ENV={
 'APP_NAME':'phase03-test','DB_PATH':'/tmp/phase03-test.db','MAX_UPLOAD_MB':'3',
 'SALAD_API_KEY':'offline-only','SALAD_API_BASE_URL':'https://example.invalid',
 'SALAD_USER_AGENT':'phase03-tests','SALAD_HTTP_TIMEOUT_SECONDS':'5',
 'SALAD_ORG':'offline','SALAD_PROJECT':'offline','SALAD_QUEUE_NAME':'offline',
 'SALAD_PRIORITY':'medium','SALAD_GPU_NAME':'offline','R2_ENDPOINT_URL':'https://example.invalid',
 'R2_BUCKET':'offline','R2_ACCESS_KEY_ID':'offline','R2_SECRET_ACCESS_KEY':'offline',
 'R2_REGION':'auto','R2_PRESIGN_TTL_SECONDS':'60'}
for name,val in FAKE_ENV.items():os.environ.setdefault(name,val)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import db, owner_api, security, identity_repository as identity, storage
from app.migrations.phase01 import migrate as phase01
from app.migrations.phase02 import migrate as phase02

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

class OwnerHTTP(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  pass
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory()
  self.path=Path(self.temp.name)/'safe-copy.sqlite'
  conn=sqlite3.connect(self.path)
  conn.executescript(LEGACY);conn.commit()
  phase01(conn);phase02(conn);conn.close()
  @contextmanager
  def connect():
   c=sqlite3.connect(self.path,timeout=5)
   c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
   try:
    with c:yield c
   finally:c.close()
  self.patch_db=patch.object(db,'connect',connect);self.patch_db.start()
  self.patch_env=patch.dict(os.environ,{'AUTH_ENABLED':'true','AUTH_PUBLIC_ORIGIN':'https://testserver',
   'AUTH_CSRF_SECRET':'Z'*48,'OWNER_ISOLATION_ENABLED':'true','AUTH_IDLE_SECONDS':'1200'})
  self.patch_env.start()
  with db.connect() as c:
   c.execute('BEGIN IMMEDIATE')
   self.a=identity.create_user(c,email='a@example.com',password='A-very-secure-pass-001',
     display_name='A',status='active',email_verified_at=security.iso())
   self.b=identity.create_user(c,email='b@example.com',password='B-very-secure-pass-002',
     display_name='B',status='active',email_verified_at=security.iso())
   _,a_token,_=security.create_session(c,self.a,False)
   _,b_token,_=security.create_session(c,self.b,False)
   self.jobs={}
   for uid,lab in ((self.a,'a'),(self.b,'b')):
    for n,state in [(1,'succeeded'),(2,'running'),(3,'failed'),(4,'pending')]:
     jid=f'{lab}-job-{n}';self.jobs[(lab,n)]=jid
     c.execute('''INSERT INTO jobs(id,request_json,variables_json,snapshot_json,state,
      created_at,updated_at,execution_mode,owner_user_id,ownership_state,client_request_id)
      VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
      (jid,'{"prompt":"secret-'+lab+'"}','{"prompt":"secret-'+lab+'"}',
       '{"positive_prompt":"secret-'+lab+'"}',state,'2026-10-01T01:00:00+00:00',
       '2026-10-01T01:00:00+00:00','direct',uid,'verified',lab+'-key-'+str(n)))
    c.execute('''INSERT INTO input_assets(asset_id,storage_key,mime_type,size_bytes,width,height,created_at,
      owner_user_id,ownership_state) VALUES (?,?,?,?,?,?,?,?,?)''',
      (lab+'-input','inputs/'+lab+'/input.png','image/png',10,1,1,security.iso(),uid,'verified'))
    c.execute('''INSERT INTO job_assets(asset_id,job_id,storage_key,media_type,mime_type,status,
      created_at,owner_user_id,ownership_state) VALUES (?,?,?,?,?,?,?,?,?)''',
      (lab+'-output',lab+'-job-1','outputs/'+lab+'-job-1/out.png','image','image/png','available',
       security.iso(),uid,'verified'))
  class Obj:
   def __init__(self,data):self.data=data
   def iter_chunks(self,chunk_size=1024*1024):yield self.data
   def close(self):pass
  def get(key):
   if key not in ('outputs/a-job-1/out.png','outputs/b-job-1/out.png'):raise KeyError('not found')
   data=b'private A bytes' if 'a-job' in key else b'private B bytes'
   return {'Body':Obj(data),'ContentLength':len(data)}
  self.patches=[patch.object(storage,'get_object',get),
    patch.object(storage,'presign_get',lambda key,ttl=None:'https://signed.example.invalid/'+key),
    patch.object(storage,'upload_fileobj',lambda f,key,content_type=None:key)]
  for p in self.patches:p.start()
  app=FastAPI();app.include_router(owner_api.router)
  self.ca=TestClient(app,base_url='https://testserver');self.cb=TestClient(app,base_url='https://testserver')
  for c,token in ((self.ca,a_token),(self.cb,b_token)):
   c.cookies.set(security.COOKIE_NAME,token);c.headers.update({'Origin':'https://testserver'})
  self.csrf_a=security.csrf_for_session(a_token)
  self.csrf_b=security.csrf_for_session(b_token)

 def tearDown(self):
  self.ca.close();self.cb.close();[p.stop() for p in reversed(self.patches)];self.patch_env.stop();self.patch_db.stop();self.temp.cleanup()

 def t(self,client,method,path,csrf=None,**kw):
  headers=kw.pop('headers',{}).copy()
  if csrf:headers['X-CSRF-Token']=csrf
  return getattr(client,method)(path,headers=headers,**kw)

 def test_01_get_job_idor(self):
  r=self.t(self.cb,'get','/api/jobs/a-job-1');self.assertEqual(r.status_code,404)
  self.assertNotIn('secret-a',r.text)
  self.assertEqual(self.t(self.ca,'get','/api/jobs/a-job-1').status_code,200)

 def test_02_list_isolation(self):
  r=self.t(self.cb,'get','/api/jobs');self.assertEqual(r.status_code,200)
  self.assertEqual(len(r.json()),4);self.assertNotIn('secret-a',r.text)

 def test_03_history_total(self):
  r=self.t(self.cb,'get','/api/jobs/history');self.assertEqual(r.json()['total'],4)
  self.assertEqual(r.json()['count'],4);self.assertNotIn('a-job',r.text)

 def test_04_history_search_prompt(self):
  r=self.t(self.cb,'get','/api/jobs/history?q=secret-a');self.assertEqual(r.json()['total'],0)
  self.assertEqual(self.t(self.ca,'get','/api/jobs/history?q=secret-a').json()['total'],4)

 def test_05_comparison_foreign(self):
  r=self.t(self.cb,'get','/api/job-comparison?first_id=b-job-1&second_id=a-job-1')
  self.assertEqual(r.status_code,404);self.assertNotIn('secret-a',r.text)

 def test_06_idempotency_lookup_foreign(self):
  self.assertEqual(self.t(self.cb,'get','/api/job-requests/a-key-1').status_code,404)
  self.assertEqual(self.t(self.ca,'get','/api/job-requests/a-key-1').status_code,200)

 def test_07_draft_foreign(self):
  self.assertEqual(self.t(self.cb,'get','/api/jobs/a-job-1/draft').status_code,404)
  self.assertIn('secret-a',self.t(self.ca,'get','/api/jobs/a-job-1/draft').text)

 def test_08_images_foreign(self):
  self.assertEqual(self.t(self.cb,'get','/api/jobs/a-job-1/images').status_code,404)
  r=self.t(self.ca,'get','/api/jobs/a-job-1/images');self.assertEqual(r.status_code,200)
  self.assertNotIn('storage_key',r.text)

 def test_09_download_foreign(self):
  self.assertEqual(self.t(self.cb,'get','/api/jobs/a-job-1/assets/a-output/download').status_code,404)
  self.assertEqual(self.t(self.ca,'get','/api/jobs/a-job-1/assets/a-output/download').content,b'private A bytes')

 def test_10_output_asset_direct(self):
  self.assertEqual(self.t(self.cb,'get','/api/assets/a-output').status_code,404)
  self.assertEqual(self.t(self.ca,'get','/api/assets/a-output').status_code,200)

 def test_11_input_asset_direct(self):
  self.assertEqual(self.t(self.cb,'get','/api/assets/a-input').status_code,404)
  self.assertEqual(self.t(self.ca,'get','/api/assets/a-input').status_code,200)

 def test_12_presign_foreign(self):
  self.assertEqual(self.t(self.cb,'post','/api/assets/a-output/download-ticket',self.csrf_b).status_code,404)
  self.assertIn('expires_in',self.t(self.ca,'post','/api/assets/a-output/download-ticket',self.csrf_a).json())

 def test_13_use_input_foreign(self):
  self.assertEqual(self.t(self.cb,'post','/api/assets/a-input/use-as-input',self.csrf_b).status_code,404)
  self.assertEqual(self.t(self.ca,'post','/api/assets/a-input/use-as-input',self.csrf_a).status_code,200)

 def test_14_cancel_foreign(self):
  self.assertEqual(self.t(self.cb,'post','/api/jobs/a-job-2/cancel',self.csrf_b).status_code,404)
  with db.connect() as c:self.assertEqual(c.execute("SELECT state FROM jobs WHERE id='a-job-2'").fetchone()[0],'running')
  self.assertEqual(self.t(self.ca,'post','/api/jobs/a-job-2/cancel',self.csrf_a).json()['state'],'cancel_requested')

 def test_15_hide_foreign(self):
  self.assertEqual(self.t(self.cb,'delete','/api/jobs/a-job-1',self.csrf_b).status_code,404)
  self.assertEqual(self.t(self.ca,'delete','/api/jobs/a-job-1',self.csrf_a).status_code,204)
  self.assertEqual(self.t(self.ca,'get','/api/jobs/a-job-1').status_code,404)

 def test_16_retry_foreign(self):
  self.assertEqual(self.t(self.cb,'post','/api/jobs/a-job-3/retry',self.csrf_b).status_code,404)
  self.assertEqual(self.t(self.ca,'post','/api/jobs/a-job-3/retry',self.csrf_a).status_code,503)

 def test_17_generation_fails_closed(self):
  self.assertEqual(self.t(self.ca,'post','/api/jobs',self.csrf_a,json={'workflow_id':'w'}).status_code,503)

 def test_18_cross_user_no_csrf(self):
  self.assertEqual(self.t(self.ca,'post','/api/jobs/a-job-2/cancel').status_code,403)
  self.assertEqual(self.t(self.cb,'post','/api/assets/a-output/download-ticket').status_code,403)

 def test_19_forged_owner_headers(self):
  r=self.t(self.cb,'get','/api/jobs/a-job-1',headers={'X-User-Id':self.a,'X-User-Role':'admin'})
  self.assertEqual(r.status_code,404)

 def test_20_missing_session(self):
  r=TestClient(self.ca.app,base_url='https://testserver')
  try:self.assertEqual(r.get('/api/jobs').status_code,401)
  finally:r.close()

 def test_21_owner_mismatch_output_asset(self):
  with db.connect() as c:
   c.execute("UPDATE job_assets SET owner_user_id=? WHERE asset_id='a-output'",(self.b,))
  self.assertEqual(self.t(self.ca,'get','/api/assets/a-output').status_code,404)
  self.assertEqual(self.t(self.cb,'get','/api/assets/a-output').status_code,404)

 def test_22_quarantined_asset(self):
  with db.connect() as c:c.execute("UPDATE input_assets SET ownership_state='quarantined' WHERE asset_id='a-input'")
  self.assertEqual(self.t(self.ca,'get','/api/assets/a-input').status_code,404)

 def test_23_quarantined_job(self):
  with db.connect() as c:c.execute("UPDATE jobs SET ownership_state='quarantined' WHERE id='a-job-1'")
  self.assertEqual(self.t(self.ca,'get','/api/jobs/a-job-1').status_code,404)

 def test_24_worker_header_is_not_user(self):
  r=TestClient(self.ca.app,base_url='https://testserver')
  try:self.assertEqual(r.get('/api/jobs',headers={'X-Worker-Token':'fake'}).status_code,401)
  finally:r.close()

 def test_25_original_owner_mismatch_download(self):
  self.assertEqual(self.t(self.ca,'get','/api/jobs/b-job-1/assets/b-output/download').status_code,404)

 def test_26_invalid_ref_does_not_disclose(self):
  self.assertEqual(self.t(self.ca,'post','/api/assets/b-output/use-as-input',self.csrf_a).status_code,404)

if __name__=='__main__':unittest.main()
