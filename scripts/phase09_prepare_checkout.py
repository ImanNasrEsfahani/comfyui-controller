#!/usr/bin/env python3
"""Phase09 exact-main+blob guarded LOCAL installer; never writes GitHub, Worker or Salad.

Copy ZIP replacement files first. Then run this script from the repository root.
"""
from __future__ import annotations
import argparse,hashlib,importlib.util,subprocess,sys
from pathlib import Path
BASE='3d7e2539cec80f7087188101fd30b38f161011ec'
BLOBS={
 'backend/app/main.py':'f3fc84226be8704e4ae4d63b63babb84ca0ea291',
 'backend/app/job_records.py':'dce59a7979b86484bfed47e6b923a06a62c4d3ff',
 'frontend/src/app/router.jsx':'4c8292f694b12814426eba8a04861c274a505062',
 'frontend/src/auth/routeUtils.js':'09beb00be38fd675262eaf5228fa00ec6137e31a',
 'frontend/src/layouts/Layouts.jsx':'925312e9f657c0387d84994bbd5a6aca6a2f0674',
}
REPLACEMENTS={
 'frontend/src/app/router.jsx':'5515584c9223e8db4b86a9eebed2c0fa76100bb1d089f5ff72132706d2436cc3',
 'frontend/src/auth/routeUtils.js':'960f4c62992a2097c7dc54cfba4ca07d46c800629b24ef16fcd835dcc856ce8a',
 'frontend/src/layouts/Layouts.jsx':'021d7fc2feab2649e75fe50360ac8b894557abe45b24bdce8d1ea761c7168635',
}
REQUIRED=('backend/app/auth.py','backend/app/owner_api.py','backend/app/registry_api.py',
 'backend/app/parameters_api.py','backend/app/workflow_api.py','backend/app/workflow_compiler.py',
 'backend/app/migrations/phase09.py','scripts/phase07_prepare_checkout.py',
 'scripts/phase08_prepare_checkout.py','scripts/phase03_prepare_checkout.py')

def blob(b):return hashlib.sha1(f'blob {len(b)}\0'.encode()+b).hexdigest()
def once(source,old,new):
 if source.count(old)!=1:raise RuntimeError('Unexpected upstream code anchor; stop and rebase')
 return source.replace(old,new,1)
def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path)
 obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj

def main_transform(source,phase08,phase07):
 if 'from .workflow_api import router as workflow_router' in source:raise RuntimeError('Phase09 router already mounted; refusing double patch')
 code=phase08.main_transform(source,phase07)
 code=once(code,'from .parameters_api import router as parameters_router\n',
   'from .parameters_api import router as parameters_router\nfrom .workflow_api import router as workflow_router\n')
 code=once(code,'        app.include_router(parameters_router)\n',
   '        app.include_router(parameters_router)\n    if os.getenv("WORKFLOW_COMPILER_ENABLED", "false").lower() == "true":\n        app.include_router(workflow_router)\n')
 return code

def run(root,apply=False):
 if not (root/'.git').is_dir():raise RuntimeError('Requires complete local Git checkout')
 head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
 if head!=BASE:raise RuntimeError('SHA changed; do not apply old Phase09 patch to new main')
 for p in REQUIRED:
  if not (root/p).is_file():raise RuntimeError('Missing prerequisite '+p)
 for p in ['backend/app/main.py','backend/app/job_records.py']:
  if blob((root/p).read_bytes())!=BLOBS[p]:raise RuntimeError('Unreviewed backend source changed: '+p)
 for p in REPLACEMENTS:
  raw=(root/p).read_bytes()
  if hashlib.sha256(raw).hexdigest()!=REPLACEMENTS[p]:
   raise RuntimeError('Frontend file is not exact Phase09 ZIP replacement: '+p)
 phase07=module(root/'scripts/phase07_prepare_checkout.py','phase07_installer')
 phase08=module(root/'scripts/phase08_prepare_checkout.py','phase08_installer')
 phase03=module(root/'scripts/phase03_prepare_checkout.py','phase03_installer')
 source=(root/'backend/app/main.py').read_text(encoding='utf-8')
 transformed=main_transform(source,phase08,phase07)
 records=phase03.transform_records((root/'backend/app/job_records.py').read_text(encoding='utf-8'))
 if apply:
  (root/'backend/app/main.py').write_text(transformed,encoding='utf-8')
  (root/'backend/app/job_records.py').write_text(records,encoding='utf-8')
 print('LOCAL APPLY complete; inspect diff and test STAGING' if apply else 'DRY RUN: source SHA, ZIP bytes and patch anchors verified')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=Path('.'));p.add_argument('--apply',action='store_true');a=p.parse_args()
 try:run(a.repo.resolve(),a.apply)
 except (RuntimeError,OSError,subprocess.CalledProcessError) as e:print('REFUSED:',e,file=sys.stderr);sys.exit(2)
