from __future__ import annotations
import importlib.util,sqlite3,sys,types
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def client(monkeypatch):
    app_pkg=types.ModuleType('phase11isolated');app_pkg.__path__=[str(ROOT/'backend/app')]
    db_mod=types.ModuleType('phase11isolated.db')
    conn=sqlite3.connect(':memory:',check_same_thread=False);conn.row_factory=sqlite3.Row
    conn.execute('CREATE TABLE schema_migrations(revision TEXT PRIMARY KEY,applied_at TEXT,checksum TEXT)')
    conn.execute('''CREATE TABLE worker_v11_observations(id TEXT PRIMARY KEY,worker_id TEXT,generation TEXT,
      image_digest TEXT,deployment_revision_id TEXT,api_ready INT,models_json TEXT,
      loras_json TEXT,nodes_json TEXT,observed_at TEXT)''')
    db_mod.connect=lambda:conn
    db_mod.utcnow=lambda:'2026-10-11T17:00:00+00:00'
    monkeypatch.setitem(sys.modules,'phase11isolated',app_pkg)
    monkeypatch.setitem(sys.modules,'phase11isolated.db',db_mod)
    spec=importlib.util.spec_from_file_location('phase11isolated.worker_v11_api',ROOT/'backend/app/worker_v11_api.py')
    mod=importlib.util.module_from_spec(spec);monkeypatch.setitem(sys.modules,spec.name,mod);spec.loader.exec_module(mod)
    api=FastAPI();api.include_router(mod.router)
    return TestClient(api),conn

def body():
    return {'worker_id':'worker-1','generation':'gen-abcdef012','worker_image_digest':'ghcr.io/company/qwen-edit@sha256:'+'a'*64,
      'deployment_revision_id':'rev-one','comfyui_api_ready':True,
      'model_versions':[{'id':'qwen-one','sha256':'a'*64,'verified':True}],
      'lora_versions':[],'node_inventory':['LoadImage','Sampler']}

def test_feature_off(client,monkeypatch):
    c,_=client;monkeypatch.setenv('DIRECT_WORKER_TOKEN','x'*48)
    assert c.post('/api/v2/worker/hello',json=body(),headers={'X-Worker-Token':'x'*48}).status_code==503

def test_browser_cookie_is_not_service_auth(client,monkeypatch):
    c,_=client;monkeypatch.setenv('DIRECT_WORKER_TOKEN','x'*48);monkeypatch.setenv('WORKER_V11_CAPABILITIES_ENABLED','true')
    assert c.post('/api/v2/worker/hello',json=body(),cookies={'session':'forged'}).status_code==401

def test_wrong_service_token(client,monkeypatch):
    c,_=client;monkeypatch.setenv('DIRECT_WORKER_TOKEN','x'*48);monkeypatch.setenv('WORKER_V11_CAPABILITIES_ENABLED','true')
    assert c.post('/api/v2/worker/hello',json=body(),headers={'X-Worker-Token':'z'*48}).status_code==401

def test_hello_observation_not_gpu_verified(client,monkeypatch):
    c,db=client;monkeypatch.setenv('DIRECT_WORKER_TOKEN','x'*48);monkeypatch.setenv('WORKER_V11_CAPABILITIES_ENABLED','true')
    res=c.post('/api/v2/worker/hello',json=body(),headers={'X-Worker-Token':'x'*48})
    assert res.status_code==200,res.text
    assert res.json()['compatibility']=='unverified' and res.json()['dispatch_enabled'] is False
    assert db.execute('SELECT count(*) FROM worker_v11_observations').fetchone()[0]==1

def test_claim_refused_without_allocator(client,monkeypatch):
    c,_=client;monkeypatch.setenv('DIRECT_WORKER_TOKEN','x'*48);monkeypatch.setenv('WORKER_V11_CAPABILITIES_ENABLED','true')
    assert c.post('/api/v2/worker/claim',headers={'X-Worker-Token':'x'*48}).status_code==503

def test_unknown_node_and_bad_digest(client,monkeypatch):
    c,_=client;monkeypatch.setenv('DIRECT_WORKER_TOKEN','x'*48);monkeypatch.setenv('WORKER_V11_CAPABILITIES_ENABLED','true')
    b=body();b['node_inventory']=['Shell;rm -rf /']
    assert c.post('/api/v2/worker/hello',json=b,headers={'X-Worker-Token':'x'*48}).status_code==422
    b=body();b['worker_image_digest']='ghcr.io/company/edit:latest'
    assert c.post('/api/v2/worker/hello',json=b,headers={'X-Worker-Token':'x'*48}).status_code==422
