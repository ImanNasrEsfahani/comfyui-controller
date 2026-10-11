#!/usr/bin/env python3
"""Exact Git HEAD, local-only Phase13 router and frontend integration.

This is a dry-run by default, and MUST NOT be run against production without
review, full test/build, backup and approved migration/deployment plan.
"""
from __future__ import annotations
import argparse,hashlib,importlib.util,os,subprocess,sys,tempfile
from pathlib import Path
BASE='a5a22d616558092e3e81504f9ed5d7061f5e0698'
BLOBS={
 'backend/app/main.py':'f3fc84226be8704e4ae4d63b63babb84ca0ea291',
 'frontend/src/app/router.jsx':'e7144754ccc73faf74331d874fac4c65cfb77e03',
 'frontend/src/auth/routeUtils.js':'0b75e6188c5027dd3baee16d2ed6b850ce233c72',
 'frontend/src/layouts/Layouts.jsx':'5ef745e3c52ee4f2d692c4abd31b71ae0d111ace',
 'frontend/src/pages/library/PrivateLibrary.jsx':'dc23c2ab0fdcc96736bdd525275e9b3bcae0fd2b',
}
FRONT=tuple(p for p in BLOBS if p.startswith('frontend/'))

def blob(value):return hashlib.sha1(f'blob {len(value)}\0'.encode()+value).hexdigest()

def stitch(composed):
 if 'video_v13_router' in composed:raise RuntimeError('Phase13 import already applied')
 a='from .scheduler_v12_api import router as scheduler_v12_router\n'
 b='app.include_router(scheduler_v12_router)\n'
 if composed.count(a)!=1 or composed.count(b)!=1:raise RuntimeError('Phase12 router anchor changed; refuse')
 composed=composed.replace(a,a+'from .video_api import router as video_v13_router\n',1)
 composed=composed.replace(b,b+'app.include_router(video_v13_router)\n',1)
 compile(composed,'backend/app/main.py','exec')
 return composed

def import_local(p):
 spec=importlib.util.spec_from_file_location('prior_phase12',p)
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def transform(original,checkout):
 previous=import_local(checkout/'scripts/phase12_prepare_checkout.py')
 return stitch(previous.main_transform(original,checkout))

def prepare(repo:Path,package:Path):
 if not (repo/'.git').exists():raise RuntimeError('Complete Git checkout required')
 head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
 if head!=BASE:raise RuntimeError('Checkout SHA changed; refuse blind patch')
 for p,expected in BLOBS.items():
  committed=subprocess.check_output(['git','-C',str(repo),'show','HEAD:'+p])
  if blob(committed)!=expected:raise RuntimeError('Committed blob differs: '+p)
  if not (repo/p).is_file():raise RuntimeError('Existing source missing: '+p)
  if p in FRONT and not (package/p).is_file():raise RuntimeError('Replacement missing: '+p)
 for p in ('scripts/phase12_prepare_checkout.py','scripts/phase11_prepare_checkout.py',
           'backend/app/video_api.py','backend/app/video_pipeline.py','backend/app/video_storage.py'):
  if not (repo/p).is_file():raise RuntimeError('Required prerequisite/source missing: '+p)
 current=repo/'backend/app/main.py'
 if blob(current.read_bytes())!=BLOBS['backend/app/main.py']:
  raise RuntimeError('Working main.py was modified; use reviewed exact blob')
 values={'backend/app/main.py':transform(current.read_text('utf-8'),repo)}
 for p in FRONT:
  present=(repo/p).read_bytes();replacement=(package/p).read_bytes()
  if present!=replacement and blob(present)!=BLOBS[p]:
   raise RuntimeError('Working frontend differs from both base and package: '+p)
  values[p]=replacement.decode('utf-8')
 return values

def run(repo:Path,package:Path,apply=False):
 values=prepare(repo,package)
 if not apply:
  print('DRY RUN OK: reviewed HEAD and blobs, no files modified. No GPU or R2 changes.');return
 for p,value in values.items():
  target=repo/p
  if target.read_text('utf-8')!=value and (repo/(p+'.phase13.bak')).exists():
   raise RuntimeError('Backup already exists: '+p)
 for p,value in values.items():
  path=repo/p
  if path.read_text('utf-8')==value:continue
  (repo/(p+'.phase13.bak')).write_bytes(path.read_bytes())
  fd,name=tempfile.mkstemp(prefix='.phase13-',dir=path.parent)
  try:
   with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(value)
   os.replace(name,path)
  finally:
   if os.path.exists(name):os.unlink(name)
 print('Local files integrated; verify git diff / full tests before any deployment. Flags remain disabled.')

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--repo',type=Path,default=Path('.'))
 ap.add_argument('--package',type=Path,default=Path('.'));ap.add_argument('--apply',action='store_true')
 args=ap.parse_args()
 try:run(args.repo.resolve(),args.package.resolve(),args.apply)
 except (OSError,RuntimeError,subprocess.CalledProcessError,SyntaxError) as err:
  print('REFUSED:',err,file=sys.stderr);raise SystemExit(2)
