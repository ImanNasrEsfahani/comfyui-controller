#!/usr/bin/env python3
"""Source-pinned LOCAL ONLY integration of previous routers + Phase11 gated hooks.

Never applies to current production, never calls GitHub APIs and never starts a
GPU. Dry run is the default. Re-applying refuses changed blobs/HEAD.
"""
from __future__ import annotations
import argparse,hashlib,importlib.util,os,subprocess,sys,tempfile
from pathlib import Path
BASE='41b11228bc4728b2781966eafb6d23fe1831cb2f'
BLOBS={'backend/app/main.py':'f3fc84226be8704e4ae4d63b63babb84ca0ea291',
       'backend/app/job_records.py':'dce59a7979b86484bfed47e6b923a06a62c4d3ff',
       'salad-worker/pull_worker.py':'3bfae4b8d14412948e6b07134d3f902e2ca69630',
       'salad-worker/Dockerfile':'5b334040781b7ffd174fc956dce7b4a0c9ed2fa8'}
NEEDS=('scripts/phase03_prepare_checkout.py','scripts/phase07_prepare_checkout.py',
       'scripts/phase08_prepare_checkout.py','scripts/phase09_prepare_checkout.py',
       'backend/app/workflow_api.py','backend/app/studio_api.py','backend/app/worker_v11_api.py',
       'salad-worker/v11_contract.py','salad-worker/v11_execution.py',
       'salad-worker/v11_cache.py','salad-worker/v11_bootstrap.py')

def blob(raw):return hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest()
def module(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def replace_once(source,old,new):
 if source.count(old)!=1:raise RuntimeError('Source anchor moved or already patched')
 return source.replace(old,new,1)

def main_patch(old,root):
 p07=module(root/'scripts/phase07_prepare_checkout.py','phase11_p07')
 p08=module(root/'scripts/phase08_prepare_checkout.py','phase11_p08')
 p09=module(root/'scripts/phase09_prepare_checkout.py','phase11_p09')
 main=p09.main_transform(old,p08,p07)
 if 'app.include_router(workflow_router)' not in main:raise RuntimeError('Previous API mounts missing')
 if 'from .studio_api import router as studio_router' not in (root/'backend/app/workflow_api.py').read_text():
  raise RuntimeError('Studio router unavailable')
 main=replace_once(main,'from .template import render_template\n',
    'from .template import render_template\nfrom .worker_v11_api import router as worker_v11_router\n')
 anchor='app = FastAPI(title=settings.app_name, version="1.3.0")\n'
 main=replace_once(main,anchor,anchor+'app.include_router(worker_v11_router)\n')
 return main

def worker_patch(old):
 if 'WORKER_V11_EXECUTION_ENABLED' in old:
  raise RuntimeError('Worker already patched')
 anchor='def build_comfy_payload(job):\n'
 old=replace_once(old,anchor,anchor+
  '    if os.environ.get("WORKER_V11_EXECUTION_ENABLED", "false").lower() == "true":\n'
  '        from v11_bootstrap import build_payload\n'
  '        return build_payload(job)\n')
 anchor='        done.set()\n        thread.join(timeout=3)\n'
 old=replace_once(old,anchor,'        if os.environ.get("WORKER_V11_EXECUTION_ENABLED", "false").lower() == "true":\n'
  '            from v11_bootstrap import cleanup_attempt\n'
  '            cleanup_attempt(job)\n'+anchor)
 # Capability self-report is observational and NEVER announces inference PASS.
 anchor='                last_hello = time.time()\n'
 old=replace_once(old,anchor,
   '                if os.environ.get("WORKER_V11_CAPABILITIES_ENABLED", "false").lower() == "true":\n'
   '                    from v11_bootstrap import capability_report\n'
   '                    request("/api/v2/worker/hello", capability_report(WORKER_ID, WORKER_GENERATION))\n'+anchor)
 return old

def docker_patch(old):
 if 'COPY v11_contract.py v11_execution.py v11_cache.py v11_bootstrap.py' in old:
  raise RuntimeError('Dockerfile already patched')
 anchor='COPY --chmod=755 pull_worker.py /opt/qvr-salad/pull_worker.py\n'
 return replace_once(old,anchor,anchor+
       'COPY v11_contract.py v11_execution.py v11_cache.py v11_bootstrap.py /opt/qvr-salad/\n')

def prepare(root):
 if not (root/'.git').exists():raise RuntimeError('A complete local Git checkout is required')
 actual=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
 if actual!=BASE:raise RuntimeError('Main HEAD advanced; rebase and review instead of blind patch')
 for p in NEEDS:
  if not (root/p).is_file():raise RuntimeError('Missing prerequisite '+p)
 for p,expected in BLOBS.items():
  if blob((root/p).read_bytes())!=expected:raise RuntimeError('Original Git blob mismatch: '+p)
 p03=module(root/'scripts/phase03_prepare_checkout.py','phase11_p03')
 return {'backend/app/main.py':main_patch((root/'backend/app/main.py').read_text(),root),
         'backend/app/job_records.py':p03.transform_records((root/'backend/app/job_records.py').read_text()),
         'salad-worker/pull_worker.py':worker_patch((root/'salad-worker/pull_worker.py').read_text()),
         'salad-worker/Dockerfile':docker_patch((root/'salad-worker/Dockerfile').read_text())}

def run(root,apply=False):
 contents=prepare(root)
 if not apply:return print('DRY RUN PASS: exact HEAD/blob guards and local patch anchors only')
 for relative in contents:
  p=root/relative
  if p.with_name(p.name+'.phase11.bak').exists():raise RuntimeError('Backup exists, refusing partial replay')
 for relative,value in contents.items():
  p=root/relative;p.with_name(p.name+'.phase11.bak').write_bytes(p.read_bytes())
  fd,tmp=tempfile.mkstemp(prefix='.phase11-',dir=p.parent)
  try:
   with os.fdopen(fd,'w',encoding='utf-8') as out:out.write(value)
   os.replace(tmp,p)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
 print('LOCAL CHECKOUT ONLY: 4 files patched, old files backed up; do not enable feature flags.')
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--repo',default='.',type=Path);a.add_argument('--apply',action='store_true');args=a.parse_args()
 try:run(args.repo.resolve(),args.apply)
 except (RuntimeError,OSError,subprocess.CalledProcessError) as e:
  print('REFUSED:',e,file=sys.stderr);sys.exit(2)
