#!/usr/bin/env python3
"""Phase10 SHA-pinned LOCAL composite installer for legacy backend router mounts.

The original main.py is intentionally untouched by published Phase03-09 ZIPs.
This stitches the reviewed Phase03/07/08/09 source transforms onto the exact
current main.py and existing job_records.py; no direct GitHub or provider writes.
"""
from __future__ import annotations
import argparse,hashlib,importlib.util,os,subprocess,sys,tempfile
from pathlib import Path
BASE='d51a4eac487bee4f69808a9e8d49016fcafe624a'
BLOBS={
 'backend/app/main.py':'f3fc84226be8704e4ae4d63b63babb84ca0ea291',
 'backend/app/job_records.py':'dce59a7979b86484bfed47e6b923a06a62c4d3ff',
}
NEEDS=('scripts/phase03_prepare_checkout.py','scripts/phase07_prepare_checkout.py',
       'scripts/phase08_prepare_checkout.py','scripts/phase09_prepare_checkout.py',
       'backend/app/auth.py','backend/app/owner_api.py','backend/app/account_api.py',
       'backend/app/media_api.py','backend/app/registry_api.py','backend/app/parameters_api.py',
       'backend/app/workflow_api.py','backend/app/studio_api.py')

def blob(b):return hashlib.sha1(f'blob {len(b)}\0'.encode()+b).hexdigest()
def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj

def prepare(root:Path):
 if not (root/'.git').exists():raise RuntimeError('Complete Git checkout required')
 head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
 if head!=BASE:raise RuntimeError('Base commit no longer matches; do NOT apply old installer')
 for path in NEEDS:
  if not (root/path).is_file():raise RuntimeError('Missing predecessor/module '+path)
 for p,sha in BLOBS.items():
  if blob((root/p).read_bytes())!=sha:raise RuntimeError('Source blob changed: '+p)
 old_main=(root/'backend/app/main.py').read_text(encoding='utf-8')
 old_records=(root/'backend/app/job_records.py').read_text(encoding='utf-8')
 phase07=module(root/'scripts/phase07_prepare_checkout.py','phase07_migration_transform')
 phase08=module(root/'scripts/phase08_prepare_checkout.py','phase08_migration_transform')
 phase09=module(root/'scripts/phase09_prepare_checkout.py','phase09_migration_transform')
 phase03=module(root/'scripts/phase03_prepare_checkout.py','phase03_migration_transform')
 new_main=phase09.main_transform(old_main,phase08,phase07)
 new_records=phase03.transform_records(old_records)
 if 'from .workflow_api import router as workflow_router' not in new_main or 'app.include_router(workflow_router)' not in new_main:
  raise RuntimeError('Phase09 router mount not found; refusing to prepare')
 if 'from .studio_api import router as studio_router' not in (root/'backend/app/workflow_api.py').read_text(encoding='utf-8'):
  raise RuntimeError('Phase10 Studio router has not been included in workflow_api.py')
 return {'backend/app/main.py':new_main,'backend/app/job_records.py':new_records}

def run(root:Path,apply:bool=False):
 prepared=prepare(root)
 if not apply:
  print('DRY RUN PASS: exact main commit + original blobs; Phase03..09 mounts compiled locally only')
  return
 for relative,content in prepared.items():
  target=root/relative;backup=target.with_name(target.name+'.phase10.bak')
  if backup.exists():raise RuntimeError('Refusing existing backup: '+str(backup))
 for relative,content in prepared.items():
  target=root/relative;backup=target.with_name(target.name+'.phase10.bak')
  original=target.read_bytes();backup.write_bytes(original)
  handle,tmp=tempfile.mkstemp(prefix='.phase10-',dir=target.parent)
  try:
   with os.fdopen(handle,'w',encoding='utf-8') as out:out.write(content)
   os.replace(tmp,target)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
 print('LOCAL FILES UPDATED WITH BACKUPS. Inspect git diff and stage on disposable DB; no production deploy performed.')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--repo',default='.',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
 try:run(a.repo.resolve(),a.apply)
 except (RuntimeError,OSError,subprocess.CalledProcessError) as e:print('REFUSED:',e,file=sys.stderr);sys.exit(2)
