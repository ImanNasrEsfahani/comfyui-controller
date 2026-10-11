#!/usr/bin/env python3
"""Exact-SHA, local-only checkout integration for Phase12; dry run default.

Does NOT alter provider/scheduler runtime, database or GitHub. The resulting
files still require a full install/build/test review before production.
"""
from __future__ import annotations
import argparse,hashlib,importlib.util,os,subprocess,sys,tempfile
from pathlib import Path
BASE='cc9cb4d6980f7d1300afc14e93b0291e36386be8'
BLOBS={'backend/app/main.py':'f3fc84226be8704e4ae4d63b63babb84ca0ea291',
 'frontend/src/app/router.jsx':'54460150fb5cf2eaebefd186a188e9c10b5843e2',
 'frontend/src/auth/routeUtils.js':'be618eded6f4bd2dc21be68a7189b3551a47be19',
 'frontend/src/layouts/Layouts.jsx':'686fbf336b4f37729283106403f10d58fa413e36'}
REPLACEMENTS=('frontend/src/app/router.jsx','frontend/src/auth/routeUtils.js','frontend/src/layouts/Layouts.jsx')

def blob(raw):return hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest()
def module(p,n):
 spec=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def main_transform(original,root):
 if 'scheduler_v12_router' in original:raise RuntimeError('Phase12 router already applied')
 previous=module(root/'scripts/phase11_prepare_checkout.py','phase12_previous')
 rendered=previous.main_patch(original,root)
 anchor='from .worker_v11_api import router as worker_v11_router\n'
 if rendered.count(anchor)!=1:raise RuntimeError('Phase11 import anchor changed')
 rendered=rendered.replace(anchor,anchor+'from .scheduler_v12_api import router as scheduler_v12_router\n',1)
 anchor='app.include_router(worker_v11_router)\n'
 if rendered.count(anchor)!=1:raise RuntimeError('Phase11 include_router anchor changed')
 rendered=rendered.replace(anchor,anchor+'app.include_router(scheduler_v12_router)\n',1)
 compile(rendered,'backend/app/main.py','exec')
 return rendered

def prepare(checkout,package):
 if not (checkout/'.git').exists():raise RuntimeError('Complete local Git checkout required')
 head=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
 if head!=BASE:raise RuntimeError('Checkout HEAD differs from reviewed main; refuse blind patch')
 for p,expected in BLOBS.items():
  # Check reviewed Git base independently from the working tree. ZIP overlay may
  # already have replaced the three UI files before this installer runs.
  committed=subprocess.check_output(['git','-C',str(checkout),'show',f'HEAD:{p}'])
  if blob(committed)!=expected:raise RuntimeError('Git HEAD original blob differs: '+p)
  if not (checkout/p).is_file():raise RuntimeError('Expected working tree file missing: '+p)
 for p in REPLACEMENTS:
  if not (package/p).is_file():raise RuntimeError('Replacement file missing: '+p)
 for p in ('scripts/phase11_prepare_checkout.py','scripts/phase09_prepare_checkout.py',
  'scripts/phase08_prepare_checkout.py','scripts/phase07_prepare_checkout.py',
  'backend/app/studio_api.py','backend/app/workflow_api.py',
  'backend/app/scheduler_v12_api.py','backend/app/scheduler_v12.py'):
  if not (checkout/p).is_file():raise RuntimeError('Missing checked prerequisite: '+p)
 if 'from .studio_api import router as studio_router' not in (checkout/'backend/app/workflow_api.py').read_text():
  raise RuntimeError('Phase10 studio install not verified')
 main_path='backend/app/main.py'
 if blob((checkout/main_path).read_bytes())!=BLOBS[main_path]:
  raise RuntimeError('Current main.py was already patched or changed; refuse replay')
 rendered={main_path:main_transform((checkout/main_path).read_text(),checkout)}
 for p in REPLACEMENTS:
  present=(checkout/p).read_bytes();replacement=(package/p).read_bytes()
  if present!=replacement and blob(present)!=BLOBS[p]:
   raise RuntimeError('Working UI file differs from both reviewed source and ZIP: '+p)
  rendered[p]=replacement.decode('utf-8')
 return rendered

def run(checkout,package,apply):
 rendered=prepare(checkout,package)
 if not apply:
  print('DRY RUN OK: exact checkout SHA, blobs and router transformations only; zero production effects');return
 for p in rendered:
  if (checkout/p).read_text()==rendered[p]:continue
  if (checkout/(p+'.phase12.bak')).exists():raise RuntimeError('Prior backup exists; refusing replay')
 for p,value in rendered.items():
  path=checkout/p
  if path.read_text()==value:continue  # ZIP replacement already overlaid
  (checkout/(p+'.phase12.bak')).write_bytes(path.read_bytes())
  fd,temp=tempfile.mkstemp(prefix='.phase12-',dir=path.parent)
  try:
   with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(value)
   os.replace(temp,path)
  finally:
   if os.path.exists(temp):os.unlink(temp)
 print('Local replacement completed. Already-overlaid UI files were verified, not overwritten. Review git diff/build; keep production flags OFF.')
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--repo',default='.',type=Path)
 parser.add_argument('--package',default='.',type=Path);parser.add_argument('--apply',action='store_true')
 x=parser.parse_args()
 try:run(x.repo.resolve(),x.package.resolve(),x.apply)
 except (OSError,RuntimeError,subprocess.CalledProcessError,SyntaxError) as exc:
  print('REFUSED:',str(exc),file=sys.stderr);sys.exit(2)
