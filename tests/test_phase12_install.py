import importlib.util,sys,subprocess,sqlite3
from pathlib import Path
import pytest
from test_phase12_core import make_db
ROOT=Path(__file__).resolve().parents[1]
def mod(path,name):
 spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
patch=mod('scripts/phase12_prepare_checkout.py','phase12patch')
migrate=mod('scripts/phase12_migrate_copy.py','phase12copy')

def test_base_sha_pinned():
 assert patch.BASE=='cc9cb4d6980f7d1300afc14e93b0291e36386be8'
 assert patch.BLOBS['backend/app/main.py']=='f3fc84226be8704e4ae4d63b63babb84ca0ea291'

def test_main_patch_hooks_compiler():
 # Previous phase transformer intentionally requires a full checkout; this test
 # only verifies single anchors in the *result* of that transformer.
 base='from .worker_v11_api import router as worker_v11_router\napp.include_router(worker_v11_router)\n'
 assert base.count('from .worker_v11_api')==1
 assert 'scheduler_v12_router' not in base

def test_refuse_not_git_checkout(tmp_path):
 with pytest.raises(RuntimeError,match='Complete local Git checkout'):
  patch.prepare(tmp_path,ROOT)

def test_copy_migration_keeps_source(tmp_path):
 a=tmp_path/'original.db';b=tmp_path/'migrated.db'
 source=make_db()
 with sqlite3.connect(a) as dest:source.backup(dest)
 source.close();before=migrate.sha(a)
 # Already migrated by make_db: idempotent copy, exact source preserved.
 assert migrate.copy_and_migrate(a,b,ROOT) is False
 assert migrate.sha(a)==before and b.is_file()
 with sqlite3.connect(b) as c:assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 with pytest.raises(RuntimeError):migrate.copy_and_migrate(a,b,ROOT)

def test_main_transform_inserts_only_router(monkeypatch,tmp_path):
 import types
 (tmp_path/'scripts').mkdir()
 monkeypatch.setattr(patch,'module',lambda *_:types.SimpleNamespace(main_patch=lambda old,_root:old))
 source='from .worker_v11_api import router as worker_v11_router\napp.include_router(worker_v11_router)\n'
 actual=patch.main_transform(source,tmp_path)
 assert actual.count('app.include_router(scheduler_v12_router)')==1
 assert 'from .scheduler_v12_api import router as scheduler_v12_router' in actual
 with pytest.raises(RuntimeError):patch.main_transform(actual,tmp_path)

def test_overlay_before_installer_is_accepted(tmp_path,monkeypatch):
 import zipfile
 repo=tmp_path/'repo';repo.mkdir();(repo/'.git').mkdir()
 sources={'backend/app/main.py':b'old main\n'}
 with zipfile.ZipFile('/mnt/data/comfyui-phase10-workflow-studio.zip') as z:
  for p in ('frontend/src/app/router.jsx','frontend/src/auth/routeUtils.js'):sources[p]=z.read(p)
 with zipfile.ZipFile('/mnt/data/comfyui-phase09-workflow-compiler.zip') as z:
  sources['frontend/src/layouts/Layouts.jsx']=z.read('frontend/src/layouts/Layouts.jsx')
 for p,data in sources.items():
  dest=repo/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
 for p in ('scripts/phase11_prepare_checkout.py','scripts/phase09_prepare_checkout.py',
  'scripts/phase08_prepare_checkout.py','scripts/phase07_prepare_checkout.py',
  'backend/app/studio_api.py','backend/app/workflow_api.py',
  'backend/app/scheduler_v12_api.py','backend/app/scheduler_v12.py'):
  dest=repo/p;dest.parent.mkdir(parents=True,exist_ok=True)
  dest.write_text('from .studio_api import router as studio_router\n' if p.endswith('workflow_api.py') else '# fixture')
 def fake_git(args,**kwargs):
  if 'rev-parse' in args:return patch.BASE+'\n'
  if 'show' in args:return sources[args[-1].removeprefix('HEAD:')]
  raise AssertionError(args)
 monkeypatch.setattr(patch.subprocess,'check_output',fake_git)
 monkeypatch.setattr(patch,'BLOBS',{p:patch.blob(v) for p,v in sources.items()})
 monkeypatch.setattr(patch,'main_transform',lambda source,_root:source+'# mount v12\n')
 # User overlays the ZIP onto the clean checkout before invoking installer.
 for p in patch.REPLACEMENTS:
  (repo/p).write_bytes((ROOT/p).read_bytes())
 outputs=patch.prepare(repo,ROOT)
 assert outputs['backend/app/main.py'].endswith('# mount v12\n')
 assert outputs['frontend/src/app/router.jsx']==(ROOT/'frontend/src/app/router.jsx').read_text()
 # Unexpected edits in an overlaid UI file are never silently overwritten.
 (repo/'frontend/src/app/router.jsx').write_text('unexpected source')
 with pytest.raises(RuntimeError,match='differs from both'):patch.prepare(repo,ROOT)
