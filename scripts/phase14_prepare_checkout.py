#!/usr/bin/env python3
"""Offline, audited-ancestry composite source EXPORT for Phase03-13 router/worker patches.

Never edits the checked-out Git worktree or production. Produces full reviewed
replacement candidates in a separate empty directory after hash/anchor checks.
Do not promote without separate full-checkout QA and operator approval.
"""
from __future__ import annotations
import argparse,hashlib,importlib.util,subprocess,sys
from pathlib import Path
BASE='8a591a3e501ba5a09751659357c625ac05babaf0'
BLOBS={
 'backend/app/main.py':'f3fc84226be8704e4ae4d63b63babb84ca0ea291',
 'backend/app/job_records.py':'dce59a7979b86484bfed47e6b923a06a62c4d3ff',
 'salad-worker/pull_worker.py':'3bfae4b8d14412948e6b07134d3f902e2ca69630',
 'salad-worker/Dockerfile':'5b334040781b7ffd174fc956dce7b4a0c9ed2fa8',
}
PREREQUISITES=('scripts/phase03_prepare_checkout.py','scripts/phase07_prepare_checkout.py',
 'scripts/phase08_prepare_checkout.py','scripts/phase09_prepare_checkout.py',
 'scripts/phase11_prepare_checkout.py','scripts/phase12_prepare_checkout.py',
 'scripts/phase13_prepare_checkout.py',
 'backend/app/owner_api.py','backend/app/auth.py','backend/app/media_api.py',
 'backend/app/workflow_api.py','backend/app/worker_v11_api.py',
 'backend/app/scheduler_v12_api.py','backend/app/video_api.py',
 'salad-worker/v11_bootstrap.py')

def blob(raw:bytes)->str:return hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest()
def load(path:Path,name:str):
 spec=importlib.util.spec_from_file_location(name,path)
 if spec is None or spec.loader is None:raise RuntimeError('Script cannot be imported: '+name)
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def prepare(root:Path):
 root=root.resolve()
 if not (root/'.git').exists():raise RuntimeError('Complete git checkout required; no synthetic clone')
 sha=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
 if sha!=BASE:
  # Phase14 itself changes HEAD; pin source ancestry and relevant Git blobs,
  # never the historical tip SHA alone. Other relevant edits still fail closed.
  ancestor=subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',BASE,sha],capture_output=True)
  if ancestor.returncode:
   raise RuntimeError('Main SHA changed outside audited ancestry; refuse transform')
  changed=subprocess.check_output(['git','-C',str(root),'diff','--name-only',BASE,sha,'--',*PREREQUISITES],text=True).strip()
  if changed:raise RuntimeError('Prerequisite source changed since audit: '+changed.replace('\n',', '))
 for f in PREREQUISITES:
  changed=subprocess.run(['git','-C',str(root),'diff','--quiet','HEAD','--',f])
  staged=subprocess.run(['git','-C',str(root),'diff','--cached','--quiet','HEAD','--',f])
  if changed.returncode or staged.returncode:
   raise RuntimeError('Prerequisite working tree changed: '+f)
 for f in PREREQUISITES:
  if not (root/f).is_file():raise RuntimeError('Missing prerequisite: '+f)
 for path,expected in BLOBS.items():
  source=subprocess.check_output(['git','-C',str(root),'show','HEAD:'+path])
  if blob(source)!=expected:raise RuntimeError('Committed blob mismatch: '+path)
  if not (root/path).is_file() or (root/path).read_bytes()!=source:
   raise RuntimeError('Working source modified: '+path)
 p13=load(root/'scripts/phase13_prepare_checkout.py','phase14_p13')
 p11=load(root/'scripts/phase11_prepare_checkout.py','phase14_p11')
 p03=load(root/'scripts/phase03_prepare_checkout.py','phase14_p03')
 main=p13.transform((root/'backend/app/main.py').read_text(encoding='utf8'),root)
 records=p03.transform_records((root/'backend/app/job_records.py').read_text(encoding='utf8'))
 worker=p11.worker_patch((root/'salad-worker/pull_worker.py').read_text(encoding='utf8'))
 docker=p11.docker_patch((root/'salad-worker/Dockerfile').read_text(encoding='utf8'))
 for path,data in (('backend/app/main.py',main),('backend/app/job_records.py',records),('salad-worker/pull_worker.py',worker)):
  compile(data,path,'exec')
 if not all(x in main for x in ('owner_router','worker_v11_router','scheduler_v12_router','video_v13_router')):
  raise RuntimeError('Composite router output incomplete')
 return {'backend/app/main.py':main,'backend/app/job_records.py':records,
         'salad-worker/pull_worker.py':worker,'salad-worker/Dockerfile':docker}

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path('.'))
 p.add_argument('--export-dir',type=Path,help='Must point to a NEW, empty, separate directory; never the checkout')
 a=p.parse_args(argv)
 try:
  source=a.repo.resolve()
  rendered=prepare(source)
  if a.export_dir:
   target=a.export_dir.resolve()
   if target==source or source in target.parents or target in source.parents:
    raise RuntimeError('Export destination must be outside the checkout')
   if target.exists():raise RuntimeError('Export destination already exists; refuse overwrite')
   for rel,data in rendered.items():
    # mkdir only after all source/hash/anchor validations have completed.
    dest=target/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(data,encoding='utf8')
   print('EXPORTED ONLY: 4 replacement candidates. No checkout files changed.')
  else:print('DRY RUN OK: exact-HEAD composite transformation computed; NO files changed')
  return 0
 except (RuntimeError,OSError,subprocess.CalledProcessError,SyntaxError) as err:
  print('REFUSED:',type(err).__name__,str(err),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
