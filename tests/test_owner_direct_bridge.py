"""Offline contract tests for owner/queue bridge; no provider, GPU or R2 access."""
from __future__ import annotations
import importlib.util
import hashlib
import json
import re
import sqlite3
import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import HTTPException

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture()
def rig(tmp_path,monkeypatch):
    path=tmp_path/'db.sqlite3'
    with sqlite3.connect(path) as c:
        c.executescript('''
        CREATE TABLE workflows(id TEXT PRIMARY KEY,name TEXT,api_prompt TEXT,updated_at TEXT,capabilities_json TEXT);
        CREATE TABLE jobs(id TEXT PRIMARY KEY,salad_job_id TEXT,workflow_id TEXT,state TEXT,request_json TEXT,
          priority TEXT,salad_queue TEXT,variables_json TEXT,created_at TEXT,updated_at TEXT,execution_mode TEXT,
          snapshot_json TEXT,client_request_id TEXT UNIQUE,request_hash TEXT,owner TEXT,source_job_id TEXT,
          queued_at TEXT,active_attempt_id TEXT,owner_user_id TEXT,ownership_state TEXT,hidden INT DEFAULT 0);
        CREATE TABLE idempotency_keys(owner_user_id TEXT,client_key TEXT,request_hash TEXT,job_id TEXT,
          created_at TEXT,expires_at TEXT, PRIMARY KEY(owner_user_id,client_key));
        CREATE TABLE input_assets(asset_id TEXT PRIMARY KEY,storage_key TEXT,owner_user_id TEXT,ownership_state TEXT);
        CREATE TABLE job_assets(asset_id TEXT PRIMARY KEY,storage_key TEXT,owner_user_id TEXT,ownership_state TEXT,
          status TEXT,job_id TEXT,attempt_id TEXT);
        ''')
        c.execute('INSERT INTO workflows VALUES(?,?,?,?,?)',('w1','Example Qwen workflow',json.dumps({
          '1':{'class_type':'UNETLoader','inputs':{'unet_name':'Qwen_Image_fp8.safetensors'}},
          '2':{'class_type':'CLIPTextEncode','inputs':{'text':'{{prompt.user}}'}}}),
          '2026-10-16T00:00:00Z',None))
        c.execute("INSERT INTO input_assets VALUES('11111111-1111-1111-1111-111111111111','inputs/owned/image.png','u1','verified')")
        c.execute("INSERT INTO input_assets VALUES('22222222-2222-2222-2222-222222222222','inputs/other/image.png','u2','verified')")
    def db_connect():
        c=sqlite3.connect(path);c.row_factory=sqlite3.Row
        return c
    def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def placeholders(graph):return sorted({v for v in re.findall(r'\{\{([^}]+)\}\}',json.dumps(graph))})
    mock_contract=SimpleNamespace(
      digest=digest,placeholders=placeholders,
      workflow_contract=lambda wf:{'workflow_version':digest(wf['api_prompt']),
                                   'capability_version':digest(wf.get('capability_spec')),
                                   'capabilities':{'references':[]}},
      validate_variables=lambda g,v: v if set(v)==set(placeholders(g)) else (_ for _ in ()).throw(ValueError('missing placeholder')),
      validate_image_references=lambda v,opt:v,
      effective_snapshot=lambda wf,v,p,**kw:{'prompt':wf['api_prompt'],'inputs':dict(v),'contract_version':1},
      ensure_no_credentials=lambda *a:None)
    db=SimpleNamespace(connect=db_connect,utcnow=lambda:'2026-10-16T00:00:00Z')
    def asset(c,uid,aid):
        r=c.execute("SELECT storage_key FROM input_assets WHERE owner_user_id=? AND ownership_state='verified' AND asset_id=?",(uid,aid)).fetchone()
        return dict(r) if r else None
    owner_repo=SimpleNamespace(require_schema=lambda c:None,asset=asset,
      job=lambda c,uid,jid:c.execute("SELECT * FROM jobs WHERE id=? AND owner_user_id=? AND ownership_state='verified' AND hidden=0",(jid,uid)).fetchone())
    package='fake_owner_bridge_'+uuid.uuid4().hex
    pack=types.ModuleType(package);pack.__path__=[];sys.modules[package]=pack
    sys.modules[package+'.db']=db
    sys.modules[package+'.contracts']=mock_contract
    sys.modules[package+'.direct_queue']=SimpleNamespace(enabled=lambda:True)
    sys.modules[package+'.owner_repository']=owner_repo
    sys.modules[package+'.settings_store']=SimpleNamespace(active=lambda:{'image':'ghcr.io/owner/worker:fp8'})
    sys.modules[package+'.config']=SimpleNamespace(settings=SimpleNamespace(r2_bucket='private-bucket',salad_priority='medium'))
    sys.modules[package+'.template']=SimpleNamespace(render_template=lambda graph,variables:graph)
    spec=importlib.util.spec_from_file_location(package+'.owner_direct_bridge',ROOT/'backend/app/owner_direct_bridge.py')
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    graph=json.loads(db_connect().execute("SELECT api_prompt FROM workflows WHERE id='w1'").fetchone()[0])
    sha=digest(graph)
    monkeypatch.setenv('OWNER_DIRECT_JOB_ENABLED','true')
    monkeypatch.setenv('OWNER_DIRECT_IMAGE','ghcr.io/owner/worker:fp8')
    monkeypatch.setenv('OWNER_DIRECT_ALLOWLIST',f'w1@{sha}')
    yield SimpleNamespace(bridge=module,conn=db_connect,path=path,sha=sha,monkeypatch=monkeypatch)
    for key in list(sys.modules):
        if key==package or key.startswith(package+'.'):sys.modules.pop(key,None)

ADMIN={'user_id':'u1','roles':['admin']}
OTHER={'user_id':'u2','roles':['admin']}
VISITOR={'user_id':'u3','roles':['user']}

def body(**changes):
    values={'client_request_id':'req1','workflow_id':'w1','variables':{'prompt.user':'A portrait'},
            'workflow_version':None,'capability_version':None,'priority':None,'source_job_id':None,'seed_mode':'fixed','reference_order':None}
    values.update(changes)
    values['model_dump']=lambda exclude=None:{key:value for key,value in values.items() if key!='model_dump' and key not in (exclude or set())}
    return SimpleNamespace(**values)

def test_catalog_exposes_unverified_and_pinned_fields(rig):
    report=rig.bridge.workflow_catalog(ADMIN)
    assert len(report['items'])==1
    row=report['items'][0]
    assert row['can_submit'] and row['readiness']=='unverified' and row['graph_sha256']==rig.sha
    assert row['model_files']==['Qwen_Image_fp8.safetensors']
    assert row['fields']==[{'key':'prompt.user','type':'text'}]

def test_admin_only_and_default_disabled(rig):
    with pytest.raises(HTTPException) as error:rig.bridge.workflow_catalog(VISITOR)
    assert error.value.status_code==403
    rig.monkeypatch.delenv('OWNER_DIRECT_JOB_ENABLED')
    assert not rig.bridge.workflow_catalog(ADMIN)['items'][0]['can_submit']
    with pytest.raises(HTTPException) as error:rig.bridge.submit(ADMIN,body())
    assert error.value.status_code==503

def test_rejects_changed_workflow_without_inserting(rig):
    with rig.conn() as c:c.execute("UPDATE workflows SET api_prompt='{}' WHERE id='w1'")
    with pytest.raises(HTTPException) as error:rig.bridge.submit(ADMIN,body())
    assert error.value.status_code==409
    with rig.conn() as c:assert c.execute('SELECT count(*) FROM jobs').fetchone()[0]==0

def test_transactional_verified_owner_and_idempotency(rig):
    first=rig.bridge.submit(ADMIN,body())
    assert first['state']=='pending' and not first['duplicate']
    again=rig.bridge.submit(ADMIN,body())
    assert again['id']==first['id'] and again['duplicate']
    with rig.conn() as c:
        row=c.execute('SELECT * FROM jobs WHERE id=?',(first['id'],)).fetchone()
        assert row['owner_user_id']=='u1' and row['ownership_state']=='verified'
        assert row['execution_mode']=='direct' and row['state']=='pending'
        assert c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]==1
        assert row['client_request_id']!='req1'
        assert json.loads(row['request_json'])['s3']['prefix']==f"outputs/{first['id']}/"
    with pytest.raises(HTTPException) as err:
        rig.bridge.submit(ADMIN,body(variables={'prompt.user':'Different!'}))
    assert err.value.status_code==409

def test_two_owners_same_request_key_are_distinct(rig):
    a=rig.bridge.submit(ADMIN,body());b=rig.bridge.submit(OTHER,body())
    assert a['id']!=b['id']
    with rig.conn() as c:
        assert c.execute('SELECT COUNT(DISTINCT client_request_id) FROM jobs').fetchone()[0]==2

def test_image_reference_owner_enforced(rig):
    key='input.image_1'
    with rig.conn() as c:
        with pytest.raises(HTTPException) as err:
            rig.bridge.resolve_references(c,'u1',{key:'asset:22222222-2222-2222-2222-222222222222'})
        assert err.value.status_code==404
        assert rig.bridge.resolve_references(c,'u1',{key:'asset:11111111-1111-1111-1111-111111111111'})[key]=='s3://private-bucket/inputs/owned/image.png'
        with pytest.raises(HTTPException):rig.bridge.resolve_references(c,'u1',{key:'https://example.com/private'})
        with pytest.raises(HTTPException):rig.bridge.resolve_references(c,'u1',{key:'s3://private-bucket/inputs/other/image.png'})

def test_direct_pin_and_operator_image_must_match(rig):
    rig.monkeypatch.setenv('OWNER_DIRECT_IMAGE','ghcr.io/evil/worker:other')
    with pytest.raises(HTTPException) as e:rig.bridge.submit(ADMIN,body())
    assert e.value.status_code==503
    rig.monkeypatch.setenv('OWNER_DIRECT_IMAGE','ghcr.io/owner/worker:fp8')
    rig.monkeypatch.setenv('OWNER_DIRECT_ALLOWLIST','w1@'+'0'*64)
    with pytest.raises(HTTPException) as e:rig.bridge.submit(ADMIN,body())
    assert e.value.status_code==409

def test_lookup_owner_isolation(rig):
    saved=rig.bridge.submit(ADMIN,body())
    assert rig.bridge.lookup_by_client_key('u1','req1')['id']==saved['id']
    assert rig.bridge.lookup_by_client_key('u2','req1') is None

def test_upload_path_not_in_renderer_or_db_without_verified_owner(rig):
    with rig.conn() as c:
        with pytest.raises(HTTPException):rig.bridge.resolve_references(c,'u1',{'input.image_2':'asset:00000000-0000-0000-0000-000000000000'})
    assert rig.bridge.filename('https://test?token=foo') is None
    assert rig.bridge.filename('../models/foo.safetensors')=='foo.safetensors'


def test_patcher_reviewed_guards_are_present():
    spec=importlib.util.spec_from_file_location('apply_bridge',ROOT/'scripts/apply_owner_direct_bridge.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    assert set(mod.REWRITE)=={'backend/app/owner_api.py','backend/app/job_records.py','frontend/src/app/router.jsx'}
    assert all(re.fullmatch('[a-f0-9]{40}',h) for h in mod.BASE.values())
    with pytest.raises(ValueError):mod.swap('something unexpected','original','replace','file')

def _asset_saver(tmp_path, owner_columns=True):
    spec=importlib.util.spec_from_file_location('apply_bridge_new',ROOT/'scripts/apply_owner_direct_bridge.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    anchor='''def save_assets(c, assets):
    for asset in assets:
        fields = list(asset)
        c.execute("INSERT INTO job_assets(" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ") ON CONFLICT(job_id,storage_key) DO NOTHING", list(asset.values()))'''
    patched=mod.change_records(anchor)
    ns={};exec(patched,{},ns)
    path=tmp_path/'asset-tests.sqlite3'
    c=sqlite3.connect(path);c.row_factory=sqlite3.Row
    jobs_owner=',owner_user_id TEXT,ownership_state TEXT' if owner_columns else ''
    assets_owner=',owner_user_id TEXT,ownership_state TEXT' if owner_columns else ''
    c.executescript(f'''CREATE TABLE jobs(id TEXT PRIMARY KEY{jobs_owner});
      CREATE TABLE job_assets(asset_id TEXT PRIMARY KEY,job_id TEXT,storage_key TEXT,
        status TEXT{assets_owner},UNIQUE(job_id,storage_key));''')
    return c,ns['save_assets']

def test_worker_output_inherits_owner_and_ignores_forged_metadata(tmp_path):
    c,save=_asset_saver(tmp_path)
    c.execute("INSERT INTO jobs VALUES('job1','user-1','verified')")
    c.execute("INSERT INTO jobs VALUES('job2',NULL,'unclaimed')")
    save(c,[{'asset_id':'a1','job_id':'job1','storage_key':'outputs/job1/a1.png',
             'status':'available','owner_user_id':'user-2','ownership_state':'verified'}])
    save(c,[{'asset_id':'a2','job_id':'job2','storage_key':'outputs/job2/a2.png','status':'available'}])
    assert tuple(c.execute("SELECT owner_user_id,ownership_state FROM job_assets WHERE asset_id='a1'").fetchone())==('user-1','verified')
    assert tuple(c.execute("SELECT owner_user_id,ownership_state FROM job_assets WHERE asset_id='a2'").fetchone())==(None,'unclaimed')
    with pytest.raises(ValueError):save(c,[{'asset_id':'other','job_id':'not-there','storage_key':'outputs/missing/a.png','status':'available'}])
    c.close()

def test_legacy_worker_storage_works_without_owner_migration(tmp_path):
    c,save=_asset_saver(tmp_path,owner_columns=False)
    c.execute("INSERT INTO jobs VALUES('legacy')")
    save(c,[{'asset_id':'a','job_id':'legacy','storage_key':'outputs/legacy/a.png','status':'available'}])
    assert c.execute('SELECT count(*) FROM job_assets').fetchone()[0]==1
    c.close()
