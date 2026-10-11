from __future__ import annotations
import importlib.util,contextlib,sys,sqlite3,types
from pathlib import Path
import pytest
from fastapi import FastAPI,HTTPException
from fastapi import Request
from fastapi.testclient import TestClient
from test_phase12_core import make_db,add,NOW
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def client(monkeypatch):
 pkg=types.ModuleType('v12isolated');pkg.__path__=[str(ROOT/'backend/app')]
 security=types.ModuleType('v12isolated.security')
 # Synthetic identity from X-Test-Identity only inside tests (NOT shipped server).
 from fastapi import Request
 def active(request:Request):
  uid=request.headers.get('X-Test-Identity')
  if not uid:raise HTTPException(401,'No session')
  return {'id':uid,'roles':['admin'] if uid=='ADMIN' else ['user']}
 def csrf(request):
  if request.headers.get('X-Test-CSRF')!='yes':raise HTTPException(403,'CSRF mismatch')
 security.require_active_user=active;security.require_csrf=csrf;security.policy=lambda:None
 database=types.ModuleType('v12isolated.db');c=make_db()
 @contextlib.contextmanager
 def connect():
  yield c
 database.connect=connect
 monkeypatch.setitem(sys.modules,'v12isolated',pkg)
 monkeypatch.setitem(sys.modules,'v12isolated.security',security)
 monkeypatch.setitem(sys.modules,'v12isolated.db',database)
 from app import scheduler_v12
 monkeypatch.setitem(sys.modules,'v12isolated.scheduler_v12',scheduler_v12)
 spec=importlib.util.spec_from_file_location('v12isolated.scheduler_v12_api',ROOT/'backend/app/scheduler_v12_api.py')
 m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
 api=FastAPI();api.include_router(m.router)
 yield TestClient(api),c
 c.close()

def auth(uid):return {'X-Test-Identity':uid}

def test_no_auth_user_scope(client,monkeypatch):
 api,c=client;monkeypatch.setenv('SCHEDULER_V12_UI_ENABLED','true')
 assert api.get('/api/v2/scheduling/me/queue-summary').status_code==401

def test_feature_disabled_default(client,monkeypatch):
 api,c=client;monkeypatch.delenv('SCHEDULER_V12_UI_ENABLED',raising=False)
 assert api.get('/api/v2/scheduling/me/queue-summary',headers=auth('A')).status_code==503

def test_own_queue_private(client,monkeypatch):
 api,c=client;monkeypatch.setenv('SCHEDULER_V12_UI_ENABLED','true')
 add(c,'A',1);add(c,'B',1);add(c,'B',2)
 a=api.get('/api/v2/scheduling/me/queue-summary',headers=auth('A'))
 b=api.get('/api/v2/scheduling/me/queue-summary',headers=auth('B'))
 assert a.status_code==200 and a.json()['eligible']==1 and b.json()['eligible']==2
 assert 'B-' not in a.text and 'A-' not in b.text

def test_admin_endpoint_denied_to_user(client,monkeypatch):
 api,c=client;monkeypatch.setenv('SCHEDULER_V12_UI_ENABLED','true')
 assert api.get('/api/v2/scheduling/admin/infrastructure',headers=auth('A')).status_code==403

def test_admin_metadata_redacted(client,monkeypatch):
 api,c=client;monkeypatch.setenv('SCHEDULER_V12_UI_ENABLED','true')
 r=api.get('/api/v2/scheduling/admin/infrastructure',headers=auth('ADMIN'))
 assert r.status_code==200 and r.json()['provider_operations_enabled'] is False
 assert all(i['readiness']=='unverified' for i in r.json()['instances'])
 assert 'prompt' not in r.text and 'storage_key' not in r.text

def test_admin_scale_requires_csrf(client,monkeypatch):
 api,c=client;monkeypatch.setenv('SCHEDULER_V12_UI_ENABLED','true')
 body={'revision_id':'rev-1','action':'stop','reason_code':'operator_review','acknowledge_non_executing_preview':True}
 assert api.post('/api/v2/scheduling/admin/scale-intents',json=body,headers=auth('ADMIN')).status_code==403

def test_user_cannot_control_gpu(client,monkeypatch):
 api,c=client;monkeypatch.setenv('SCHEDULER_V12_UI_ENABLED','true')
 body={'revision_id':'rev-1','action':'stop','reason_code':'operator_review','acknowledge_non_executing_preview':True}
 assert api.post('/api/v2/scheduling/admin/scale-intents',json=body,headers={**auth('A'),'X-Test-CSRF':'yes'}).status_code==403

def test_admin_stop_is_not_real_provider_command(client,monkeypatch):
 api,c=client;monkeypatch.setenv('SCHEDULER_V12_UI_ENABLED','true')
 body={'revision_id':'rev-1','action':'stop','reason_code':'operator_review','acknowledge_non_executing_preview':True}
 r=api.post('/api/v2/scheduling/admin/scale-intents',json=body,headers={**auth('ADMIN'),'X-Test-CSRF':'yes'})
 assert r.status_code==202 and r.json()['state']=='requested' and not r.json()['submitted_to_provider']

def test_admin_scale_requires_acknowledgment(client,monkeypatch):
 api,c=client;monkeypatch.setenv('SCHEDULER_V12_UI_ENABLED','true')
 body={'revision_id':'rev-1','action':'stop','reason_code':'operator_review','acknowledge_non_executing_preview':False}
 assert api.post('/api/v2/scheduling/admin/scale-intents',json=body,headers={**auth('ADMIN'),'X-Test-CSRF':'yes'}).status_code==422
