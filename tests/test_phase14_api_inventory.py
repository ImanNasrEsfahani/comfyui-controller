from pathlib import Path
import importlib.util,json
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('phase14_api',ROOT/'scripts/phase14_api_inventory.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_unmounted_router_fails_closed(tmp_path):
    root=tmp_path/'backend/app';root.mkdir(parents=True)
    (root/'main.py').write_text('from fastapi import FastAPI\napp=FastAPI()\n')
    (root/'owner_api.py').write_text('router=object()\n')
    result=m.static_inventory(tmp_path)
    assert result['readiness']=='BLOCKED'
    assert result['modules']['owner_api']['source_present'] is True
    assert result['modules']['owner_api']['router_mount_observed'] is False

def test_exact_router_mount_detected(tmp_path):
    root=tmp_path/'backend/app';root.mkdir(parents=True)
    (root/'main.py').write_text('from .owner_api import router as owner_router\napp.include_router(owner_router)\n')
    r=m.static_inventory(tmp_path)
    assert r['modules']['owner_api']['router_mount_observed']
    assert r['readiness']=='BLOCKED'  # Other required routers still absent.

def test_import_only_does_not_pretend_mounted(tmp_path):
    root=tmp_path/'backend/app';root.mkdir(parents=True)
    (root/'main.py').write_text('from .owner_api import router as owner_router\n')
    assert not m.static_inventory(tmp_path)['modules']['owner_api']['router_mount_observed']

def test_source_syntax_error(tmp_path):
    root=tmp_path/'backend/app';root.mkdir(parents=True)
    (root/'main.py').write_text('def x(\n')
    try:m.static_inventory(tmp_path)
    except SyntaxError:return
    assert False,'must reject invalid module'
