from __future__ import annotations
import contextlib,importlib.util,sqlite3,sys,types
from pathlib import Path
import pytest
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import Response
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]

def make_db():
 c=sqlite3.connect(':memory:',check_same_thread=False);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
 c.executescript('''
 CREATE TABLE schema_migrations(revision TEXT PRIMARY KEY,applied_at TEXT,checksum TEXT);
 CREATE TABLE users(id TEXT PRIMARY KEY);
 CREATE TABLE jobs(id TEXT PRIMARY KEY,owner_user_id TEXT,ownership_state TEXT,active_attempt_id TEXT);
 CREATE TABLE job_assets(asset_id TEXT PRIMARY KEY,job_id TEXT,owner_user_id TEXT,ownership_state TEXT,status TEXT,mime_type TEXT,attempt_id TEXT,storage_key TEXT);
 CREATE TABLE input_assets(asset_id TEXT PRIMARY KEY,owner_user_id TEXT,ownership_state TEXT,mime_type TEXT,storage_key TEXT);
 CREATE TABLE asset_variants(id TEXT PRIMARY KEY,asset_id TEXT,owner_user_id TEXT,kind TEXT,storage_key TEXT,mime_type TEXT);
 CREATE TABLE asset_deletions(asset_id TEXT,owner_user_id TEXT);
 CREATE TABLE model_families(id TEXT PRIMARY KEY,name TEXT,modality TEXT);
 CREATE TABLE model_versions(id TEXT PRIMARY KEY,family_id TEXT,status TEXT,revision TEXT,capabilities_json TEXT);
 CREATE TABLE worker_images(id TEXT PRIMARY KEY,signature_status TEXT,status TEXT);
 CREATE TABLE image_model_compatibility(image_id TEXT,model_id TEXT,state TEXT);
 CREATE TABLE deployment_profile_revisions(id TEXT PRIMARY KEY,image_id TEXT,status TEXT);
 CREATE TABLE deployment_profiles(id TEXT PRIMARY KEY,active_revision_id TEXT);
 CREATE TABLE model_deployment_compatibility(revision_id TEXT,model_id TEXT,state TEXT);
 INSERT INTO users VALUES ('A'),('B');
 INSERT INTO input_assets VALUES('videoA','A','verified','video/mp4','inputs/A/video.mp4');
 INSERT INTO input_assets VALUES('imageA','A','verified','image/png','inputs/A/a.png');
 INSERT INTO input_assets VALUES('imageB','B','verified','image/png','inputs/B/b.png');
 ''')
 return c

@pytest.fixture
def case(monkeypatch):
 pkg=types.ModuleType('v13isolated');pkg.__path__=[str(ROOT/'backend/app')];monkeypatch.setitem(sys.modules,'v13isolated',pkg)
 c=make_db();
 db=types.ModuleType('v13isolated.db')
 @contextlib.contextmanager
 def connect():yield c
 db.connect=connect;monkeypatch.setitem(sys.modules,'v13isolated.db',db)
 security=types.ModuleType('v13isolated.security')
 def active(request:Request):
  u=request.headers.get('X-Test-Uid')
  if not u:raise HTTPException(401,'Unauthenticated')
  return {'user_id':u}
 def csrf(request:Request):
  if request.headers.get('X-Test-Csrf')!='true':raise HTTPException(403,'CSRF')
 security.require_active_user=active;security.require_csrf=csrf;monkeypatch.setitem(sys.modules,'v13isolated.security',security)
 media=types.ModuleType('v13isolated.media_repository')
 def asset(conn,uid,aid):
  row=conn.execute("SELECT * FROM input_assets WHERE asset_id=? AND owner_user_id=? AND ownership_state='verified'",(aid,uid)).fetchone()
  if row is None or conn.execute('SELECT 1 FROM asset_deletions WHERE asset_id=? AND owner_user_id=?',(aid,uid)).fetchone():return None
  return dict(row)
 media.available_asset=asset;monkeypatch.setitem(sys.modules,'v13isolated.media_repository',media)
 media_api=types.ModuleType('v13isolated.media_api')
 media_api.ready=lambda:None
 def source(conn,uid,aid):
  result=asset(conn,uid,aid)
  if result is None:raise HTTPException(404,'Not found')
  return result
 media_api.source=source
 media_api.stream_object=lambda key,kind,**kw:Response(content='FAKE_BYTES',headers={'X-Demo-Kind':kind})
 monkeypatch.setitem(sys.modules,'v13isolated.media_api',media_api)
 def local(name):
  spec=importlib.util.spec_from_file_location('v13isolated.'+name,ROOT/'backend/app'/f'{name}.py')
  m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m
 pipeline=local('video_pipeline');api=local('video_api')
 from v13isolated.migrations import phase13
 phase13.migrate(c)
 app=FastAPI();app.include_router(api.router)
 monkeypatch.setenv('VIDEO_V13_ENABLED','true')
 yield TestClient(app),c,api
 c.close()

def hdr(uid='A',csrf=False):return {'X-Test-Uid':uid,**({'X-Test-Csrf':'true'} if csrf else {})}

def register(c):
 import json
 policy={'video':{'runtime_tested':True,'evidence_ref':'synthetic-only','intents':['text2video','image2video'],
                'dimensions':[[512,512]],'fps':[16],'max_seconds':4,'codecs':['h264']}}
 c.executescript('''
 INSERT INTO model_families VALUES ('family','Testing','video');
 INSERT INTO worker_images VALUES ('img','verified','approved');
 INSERT INTO deployment_profile_revisions VALUES('rev','img','active');
 INSERT INTO deployment_profiles VALUES('prof','rev');
 INSERT INTO image_model_compatibility VALUES('img','v-model','tested_pass');
 INSERT INTO model_deployment_compatibility VALUES('rev','v-model','tested_pass');
 ''')
 c.execute('INSERT INTO model_versions VALUES(?,?,?,?,?)',('v-model','family','ready','1',json.dumps(policy)))
 c.commit()

def body(intent='text2video'):
 data={'model_version_id':'v-model','intent':intent,'prompt':'hello','seconds':3,'fps':16,'width':512,'height':512,'seed':'0','codec':'h264'}
 if intent=='image2video':data['start_frame']='imageA'
 return data

def test_no_session(case):
 api,c,m=case
 assert api.get('/api/v2/video/models').status_code==401

def test_gate_off(case,monkeypatch):
 api,c,m=case;monkeypatch.setenv('VIDEO_V13_ENABLED','false')
 assert api.get('/api/v2/video/models',headers=hdr()).status_code==503

def test_no_models_claimed_ready(case):
 api,c,m=case
 assert api.get('/api/v2/video/models',headers=hdr()).json()=={'items':[],'gpu_execution_enabled':False}

def test_preflight_requires_admin_registered_evidence(case):
 api,c,m=case
 assert api.post('/api/v2/video/validate',headers=hdr(csrf=True),json=body()).status_code==503

def test_registry_public_safe_no_worker_ready(case):
 api,c,m=case;register(c)
 item=api.get('/api/v2/video/models',headers=hdr()).json()['items'][0]
 assert item['generate_enabled'] is False and item['readiness']=='unverified_worker'
 assert 'synthetic-only' not in str(item)

def test_preview_without_csrf_denied(case):
 api,c,m=case;register(c)
 assert api.post('/api/v2/video/validate',headers=hdr(),json=body()).status_code==403

def test_preview_success_but_no_job(case):
 api,c,m=case;register(c)
 result=api.post('/api/v2/video/validate',headers=hdr(csrf=True),json=body())
 assert result.status_code==200 and result.json()['valid'] and not result.json()['dispatch_allowed']
 assert 'hello' not in result.text

def test_validate_wrong_user_image(case):
 api,c,m=case;register(c)
 r=api.post('/api/v2/video/validate',headers=hdr('B',True),json=body('image2video'))
 assert r.status_code==422 and r.json()['detail']=='VIDEO_ASSET_DENIED'

def test_validate_own_image(case):
 api,c,m=case;register(c)
 assert api.post('/api/v2/video/validate',headers=hdr('A',True),json=body('image2video')).status_code==200

def test_jobs_never_dispatch(case):
 api,c,m=case;register(c)
 r=api.post('/api/v2/video/jobs',headers=hdr('A',True),json=body())
 assert r.status_code==503 and not c.execute('SELECT 1 FROM jobs').fetchone()

def test_original_owner_only(case):
 api,c,m=case
 assert api.get('/api/v2/video/assets/videoA/original',headers=hdr('B')).status_code==404
 assert api.get('/api/v2/video/assets/videoA/original',headers=hdr('A')).status_code==200

def test_missing_poster_keeps_original(case):
 api,c,m=case
 assert api.get('/api/v2/video/assets/videoA/poster',headers=hdr()).status_code==404
 assert api.get('/api/v2/video/assets/videoA/original',headers=hdr()).status_code==200

def test_provenance_variant_owner_only(case):
 api,c,m=case
 c.execute("INSERT INTO video_media_details VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
  ('videoA','A','input','video/mp4','h264',128,128,1,10,400,'a'*64,'2026-01-01'))
 c.execute("INSERT INTO asset_variants VALUES(?,?,?,?,?,?)",('poster1','videoA','A','poster','inputs/A/poster.jpg','image/jpeg'))
 c.execute("INSERT INTO video_transcode_tasks(id,asset_id,owner_user_id,kind,status,verified_storage_key,sha256,created_at) VALUES(?,?,?,?,?,?,?,?)",
  ('task1','videoA','A','poster','ready','inputs/A/poster.jpg','b'*64,'2026-01-01'))
 c.commit()
 assert api.get('/api/v2/video/assets/videoA/poster',headers=hdr('A')).status_code==200
 assert api.get('/api/v2/video/assets/videoA/poster',headers=hdr('B')).status_code==404

def test_reuse_slot_contract(case):
 api,c,m=case
 r=api.post('/api/v2/video/assets/videoA/reuse?slot=reference',headers=hdr('A',True));assert r.status_code==422
 r=api.post('/api/v2/video/assets/videoA/reuse?slot=source_video',headers=hdr('A',True));assert r.status_code==200 and r.json()['draft_only']
 assert api.post('/api/v2/video/assets/videoA/reuse?slot=source_video',headers=hdr('B',True)).status_code==404
