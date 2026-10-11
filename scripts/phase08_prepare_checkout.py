#!/usr/bin/env python3
"""Phase08 exact-main, exact-Git-blob local patcher (no GitHub writes).

The base GitHub main has Phase07 registry modules but original, unmounted main.py;
installing P08 must also mount the prerequisite routers and patch worker ownership.
"""
from __future__ import annotations
import argparse,hashlib,importlib.util,subprocess,sys
from pathlib import Path
BASE='6afe73e12b74e7c16c94bc9b4c1d6dac7db06588'
BLOBS={'backend/app/main.py':'f3fc84226be8704e4ae4d63b63babb84ca0ea291',
       'backend/app/job_records.py':'dce59a7979b86484bfed47e6b923a06a62c4d3ff',
       'frontend/src/app/router.jsx':'234f306d38ed1c24501c13ea497196fa822706b2',
       'frontend/src/auth/routeUtils.js':'86665b7bc5eddd9cdc6869778c85bc7e878fbdf2',
       'frontend/src/layouts/Layouts.jsx':'7f1869f1742f8fc32f9733d899cb6f39f11dc69e'}
REPLACEMENT_SHA256={'frontend/src/app/router.jsx':'d8db1a2acd774ff8b1b8e114dfabae215485b42550e96984a50af411336053f5',
 'frontend/src/auth/routeUtils.js':'fc0ca6b083a376fdea6bc0684a2d33b3414fdcedaa2edacf10093a08ce1a6d71',
 'frontend/src/layouts/Layouts.jsx':'8840f5beaf33e2dc9c6fab8f6c936b45740a811a2877d7221e7ca865dbafbda5'}
REQUIRED=('backend/app/auth.py','backend/app/owner_api.py','backend/app/registry_api.py',
          'backend/app/parameters_api.py','backend/app/dynamic_params.py',
          'backend/app/migrations/phase07.py','backend/app/migrations/phase08.py',
          'scripts/phase03_prepare_checkout.py','scripts/phase07_prepare_checkout.py')

def blob(raw):return hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest()
def once(source,old,new):
 if source.count(old)!=1:raise RuntimeError('Source changed, anchor not unique: '+old[:80])
 return source.replace(old,new,1)
def module_at(path,name):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def main_transform(source,phase07):
 code=phase07.main_transform(source)
 code=once(code,'from .registry_api import router as registry_router\n',
  'from .registry_api import router as registry_router\nfrom .parameters_api import router as parameters_router\n')
 code=once(code,'    app.include_router(registry_router)\n',
  '    app.include_router(registry_router)\n    if os.getenv("DYNAMIC_PARAMETERS_ENABLED", "false").lower() == "true":\n        app.include_router(parameters_router)\n')
 return code

def full_frontend(root:Path,phase07):
 router=phase07.router_transform((root/'frontend/src/app/router.jsx').read_text())
 router=once(router,"import {Phase06JobDetails} from '../pages/library/Phase06Jobs.jsx';\n",
  "import {Phase06JobDetails} from '../pages/library/Phase06Jobs.jsx';\nimport {ParameterStudio,PresetsPage} from '../pages/parameters/ParameterPages.jsx';\n")
 router=once(router,"  else if(route.path==='/jobs'){title='کارهای من';node=<JobsPage/>;}",
  "  else if(route.path==='/presets'){title='Presetهای من';node=<PresetsPage/>;}\n  else if(route.path==='/jobs'){title='کارهای من';node=<JobsPage/>;}")
 router=once(router,'node=<><CreateImagePage/><ReferenceDraftPanel/></>;', 'node=<><ParameterStudio/><ReferenceDraftPanel/></>;')
 layouts=phase07.layouts_transform((root/'frontend/src/layouts/Layouts.jsx').read_text())
 layouts=once(layouts,"['/tools','مدل‌ها'],", "['/tools','مدل‌ها'],['/presets','Presetهای من'],")
 route_utils=phase07.route_utils((root/'frontend/src/auth/routeUtils.js').read_text())
 return {'frontend/src/app/router.jsx':router,'frontend/src/layouts/Layouts.jsx':layouts,
         'frontend/src/auth/routeUtils.js':route_utils}

def run(root:Path,apply:bool):
 if not (root/'.git').is_dir():raise RuntimeError('Complete Git checkout required')
 head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
 if head!=BASE:raise RuntimeError('Latest main differs from verified source SHA; DO NOT apply')
 # These three frontend files may already have been replaced by the ZIP.
 # Accept only ALL original blobs or ALL exact package replacement hashes.
 source_kinds=[]
 for name,expected in BLOBS.items():
  path=root/name
  if not path.is_file():raise RuntimeError('Missing source '+name)
  raw=path.read_bytes()
  if not name.startswith('frontend/'):
   if blob(raw)!=expected:raise RuntimeError('Unreviewed backend blob: '+name)
  elif blob(raw)==expected:source_kinds.append('original')
  elif hashlib.sha256(raw).hexdigest()==REPLACEMENT_SHA256[name]:source_kinds.append('replaced')
  else:raise RuntimeError('Unreviewed frontend blob: '+name)
 if len(set(source_kinds))!=1:raise RuntimeError('Partial frontend replacement detected; stop')
 mode=source_kinds[0]
 for name in REQUIRED:
  if not (root/name).is_file():raise RuntimeError('Missing prerequisite file: '+name)
 phase07=module_at(root/'scripts/phase07_prepare_checkout.py','phase07_patcher')
 phase03=module_at(root/'scripts/phase03_prepare_checkout.py','phase03_patcher')
 # Phase07 helpers only transform original sources; compare prebuilt JSX separately.
 transformed={'backend/app/main.py':main_transform((root/'backend/app/main.py').read_text(),phase07),
   'backend/app/job_records.py':phase03.transform_records((root/'backend/app/job_records.py').read_text())}
 if mode=='original':
  expected=full_frontend(root,phase07)
  for name,content in expected.items():
   if hashlib.sha256(content.encode()).hexdigest()!=REPLACEMENT_SHA256[name]:
    raise RuntimeError('Generated frontend differs from audited package: '+name)
 else:
  expected={name:(root/name).read_text() for name in REPLACEMENT_SHA256}
 if apply:
  for p,content in {**transformed,**expected}.items():(root/p).write_text(content,encoding='utf-8')
 print('APPLIED (inspect diff before staging)' if apply else 'DRY RUN PASS: audited frontend '+mode,', '.join(transformed))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=Path('.'));p.add_argument('--apply',action='store_true');args=p.parse_args()
 try:run(args.repo.resolve(),args.apply)
 except (OSError,RuntimeError,subprocess.CalledProcessError) as e:print('Refused:',e,file=sys.stderr);sys.exit(2)
