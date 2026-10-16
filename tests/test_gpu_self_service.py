"""Self-service GPU controls: offline tests, no provider credentials or GPUs."""
from __future__ import annotations
import importlib.util
import sqlite3
import sys
import types
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture

def service(monkeypatch):
    prefix='gpu_sandbox_'+uuid4().hex
    package=types.ModuleType(prefix);package.__path__=[]
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
    conn.execute('CREATE TABLE jobs(execution_mode TEXT,state TEXT)')
    def context():
        class Conn:
            def __enter__(self):return conn
            def __exit__(self,*args):pass
        return Conn()
    call=Mock(return_value={'accepted':True,'pending':True})
    provider=types.SimpleNamespace(
        status=Mock(return_value={'status':'started','replicas':1,'pending_change':False,
                                  'instances':[{'id':'secret-node','state':'running','ready':True,
                                                'pulling_progress':99}], 'keep_warm':False,
                                  'auto_gpu_control':False}),
        start=Mock(return_value={'accepted':True}),
        request_one_replica=Mock(return_value={'accepted':True}),
        set_replicas=Mock(return_value={'accepted':True}),
        stop=Mock(return_value={'accepted':True}),
    )
    for name,object_ in {
      'db':types.SimpleNamespace(connect=context),
      'direct_queue':types.SimpleNamespace(enabled=lambda:True),
      'salad_control':provider,
      'security':types.SimpleNamespace(require_active_user=lambda:None,require_csrf=Mock()),
    }.items():
        sys.modules[prefix+'.'+name]=object_
    sys.modules[prefix]=package
    spec=importlib.util.spec_from_file_location(prefix+'.gpu_self_service',ROOT/'backend/app/gpu_self_service.py')
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
    try:yield m,conn,provider,sys.modules[prefix+'.security']
    finally:
        conn.close()
        for key in list(sys.modules):
            if key==prefix or key.startswith(prefix+'.'):sys.modules.pop(key,None)

def test_status_is_aggregated_and_private(service):
    api,db,provider,_=service
    db.execute("INSERT INTO jobs VALUES('direct','pending')")
    db.execute("INSERT INTO jobs VALUES('direct','running')")
    db.execute("INSERT INTO jobs VALUES('salad_queue','pending')")
    response=api.status(user={'user_id':'any-user','roles':['user']})
    assert response['queue']=={'waiting':1,'active':1,'uncertain':0}
    assert response['replicas']==1 and response['instances'][0]['ready']
    assert 'secret-node' not in str(response)

def test_any_signed_in_user_can_start_without_admin_flag(service):
    api,db,provider,security=service
    result=api.control('start',request=object(),user={'user_id':'basic','roles':['user']})
    assert result['action']=='start'
    provider.start.assert_called_once_with(source='self_service')
    security.require_csrf.assert_called_once()

def test_any_user_can_ask_for_one_gpu(service):
    api,db,provider,_=service
    result=api.control('one',request=object(),user={'user_id':'basic','roles':['user']})
    assert result['action']=='one'
    provider.request_one_replica.assert_called_once_with(source='self_service')

def test_stop_refused_if_other_user_has_queued_work(service):
    api,db,provider,_=service
    db.execute("INSERT INTO jobs VALUES('direct','pending')")
    with pytest.raises(HTTPException) as err:
        api.control('stop',request=object(),user={'user_id':'other','roles':['user']})
    assert err.value.status_code==409
    provider.stop.assert_not_called()

def test_scale_zero_refused_while_active_job(service):
    api,db,provider,_=service
    db.execute("INSERT INTO jobs VALUES('direct','finalizing')")
    with pytest.raises(HTTPException) as err:
        api.control('zero',request=object(),user={'user_id':'any','roles':['user']})
    assert err.value.status_code==409
    provider.set_replicas.assert_not_called()

def test_stop_can_succeed_when_idle(service):
    api,db,provider,_=service
    result=api.control('stop',request=object(),user={'user_id':'any','roles':['user']})
    assert result['action']=='stop'
    provider.stop.assert_called_once_with(source='self_service')

def test_csrf_protected_even_for_logged_in_user(service):
    api,db,provider,security=service
    security.require_csrf.side_effect=HTTPException(403,'missing csrf')
    with pytest.raises(HTTPException) as err:
        api.control('start',request=object(),user={'user_id':'basic'})
    assert err.value.status_code==403
    provider.start.assert_not_called()

def test_provider_failure_is_sanitized(service):
    api,db,provider,_=service
    provider.start.side_effect=ConnectionError('provider-secret-token-abc')
    with pytest.raises(HTTPException) as err:
        api.control('start',request=object(),user={'user_id':'basic'})
    assert err.value.status_code==502
    assert 'secret' not in str(err.value.detail)

def test_integrated_backend_and_frontend_use_self_service_routes():
    entry=(ROOT/'backend/app/integrated_main.py').read_text()
    router=(ROOT/'frontend/src/app/router.jsx').read_text()
    panel=(ROOT/'frontend/src/pages/legacy-direct/LegacyDirectPanel.jsx').read_text()
    assert 'gpu_self_service_router' in entry
    assert "('/api/self-service/gpu', 'GET')" in entry
    assert 'node=<LegacyDirectPanel/>' in router
    assert 'node=<><LegacyDirectPanel/><ParameterStudio/>' not in router
    assert "'/api/self-service/gpu/start'" in panel
    assert "'/api/self-service/gpu/stop'" in panel
    assert "session.user?.roles?.some" not in panel
