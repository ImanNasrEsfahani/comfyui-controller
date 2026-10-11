#!/usr/bin/env python3
"""Only SHA-verified full Git checkout; additive local rewrite, no GitHub write operations."""
from __future__ import annotations
import argparse,hashlib,subprocess,sys,importlib.util
from pathlib import Path
BASE='b54e99a2602449d55e66a72b7ba6e59390720621'
BLOBS={
 'backend/app/main.py':'f3fc84226be8704e4ae4d63b63babb84ca0ea291',
 'backend/app/job_records.py':'dce59a7979b86484bfed47e6b923a06a62c4d3ff',
 'frontend/src/app/router.jsx':'234f306d38ed1c24501c13ea497196fa822706b2',
 'frontend/src/auth/routeUtils.js':'86665b7bc5eddd9cdc6869778c85bc7e878fbdf2',
 'frontend/src/layouts/Layouts.jsx':'7f1869f1742f8fc32f9733d899cb6f39f11dc69e'}
def blob(data):return hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()
def once(text,old,new):
 if text.count(old)!=1:raise RuntimeError('Source anchor mismatch: '+repr(old[:80]))
 return text.replace(old,new,1)
def main_transform(text):
 imp='from . import db, storage, salad, salad_control, job_lifecycle, settings_store, direct_queue, contracts\n'
 text=once(text,imp,imp+'from .auth import router as auth_router\nfrom .owner_api import router as owner_router\nfrom .account_api import router as account_router\nfrom .media_api import router as media_router\nfrom .registry_api import router as registry_router\n')
 app='app = FastAPI(title=settings.app_name, version="1.3.0")\n'
 routers=('app.include_router(auth_router)\n'
  'if os.getenv("MODEL_REGISTRY_ENABLED", "false").lower() == "true":\n    app.include_router(registry_router)\n'
  'if os.getenv("MEDIA_LIBRARY_ENABLED", "false").lower() == "true":\n    app.include_router(media_router)\n'
  'if os.getenv("OWNER_ISOLATION_ENABLED", "false").lower() == "true":\n    app.include_router(owner_router)\n'
  'if os.getenv("ACCOUNT_UI_ENABLED", "false").lower() == "true":\n    app.include_router(account_router)\n')
 return once(text,app,app+routers)
def route_utils(text):
 text=once(text,"'/admin/deployment-profiles', '/admin/users'","'/admin/deployment-profiles', '/admin/models', '/admin/worker-images', '/admin/users'")
 text=once(text,'return USER_ROUTES.includes(path) ||',"return /^\\/models\\/[A-Za-z0-9_-]{1,96}$/.test(path) || USER_ROUTES.includes(path) ||")
 text=once(text,"  if (normalized === '/admin/jobs')", "  if (/^\\/models\\/[A-Za-z0-9_-]{1,96}$/.test(normalized)) return {scope:'user',path:normalized};\n  if (normalized === '/admin/jobs')")
 return text
def router_transform(text):
 s="import {Phase06JobDetails} from '../pages/library/Phase06Jobs.jsx';\n"
 text=once(text,s,s+"import {ToolsCatalog,ModelDetails,AdminModels,AdminWorkerImages,AdminDeploymentProfiles} from '../pages/registry/RegistryPages.jsx';\n")
 s='    else if(route.path!==\'/admin\')adminNode=<UnsupportedPage title="ابزار مدیریت"/>;'
 text=once(text,s,'''    else if(route.path==='/admin/models'){adminTitle='مدل‌ها';adminNode=<AdminModels/>;}
    else if(route.path==='/admin/worker-images'){adminTitle='Worker Images';adminNode=<AdminWorkerImages/>;}
    else if(route.path==='/admin/deployment-profiles'){adminTitle='Deployment Profiles';adminNode=<AdminDeploymentProfiles/>;}
'''+s)
 s="  if(route.path==='/jobs'){title='کارهای من';node=<JobsPage/>;}"
 text=once(text,s,"  if(route.path==='/tools'){title='کاتالوگ';node=<ToolsCatalog/>;}\n  else if(route.path.startsWith('/models/')){title='مدل';node=<ModelDetails id={route.path.split('/')[2]}/>;}\n  else if(route.path==='/jobs'){title='کارهای من';node=<JobsPage/>;}")
 return text

def layouts_transform(text):
 text=once(text,"['/library','کتابخانه'],", "['/library','کتابخانه'],['/tools','مدل‌ها'],")
 text=once(text,"[['/admin','مدیریت']]", "[['/admin','مدیریت'],['/admin/models','مدل‌ها'],['/admin/worker-images','Worker Images'],['/admin/deployment-profiles','Deployment Profiles']]")
 return text

def transform(root:Path):
 for p,expected in BLOBS.items():
  f=root/p
  if not f.is_file() or blob(f.read_bytes())!=expected:raise RuntimeError('Unexpected source blob: '+p)
 for dep in ['backend/app/registry_api.py','backend/app/migrations/phase07.py',
             'frontend/src/pages/registry/RegistryPages.jsx','scripts/phase03_prepare_checkout.py']:
  if not (root/dep).is_file():raise RuntimeError('Missing dependency: '+dep)
 spec=importlib.util.spec_from_file_location('phase03_patcher',root/'scripts/phase03_prepare_checkout.py')
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return {'backend/app/main.py':main_transform((root/'backend/app/main.py').read_text()),
         'backend/app/job_records.py':module.transform_records((root/'backend/app/job_records.py').read_text()),
         'frontend/src/app/router.jsx':router_transform((root/'frontend/src/app/router.jsx').read_text()),
         'frontend/src/auth/routeUtils.js':route_utils((root/'frontend/src/auth/routeUtils.js').read_text()),
         'frontend/src/layouts/Layouts.jsx':layouts_transform((root/'frontend/src/layouts/Layouts.jsx').read_text())}

def run(root:Path,apply:bool):
 if not (root/'.git').is_dir():raise RuntimeError('Requires full Git checkout')
 head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
 if head!=BASE:raise RuntimeError('Branch changed; stop and rebuild from latest main')
 transformed=transform(root)
 if apply:
  for p,value in transformed.items():(root/p).write_text(value,encoding='utf-8')
 print('APPLIED' if apply else 'DRY-RUN PASS',', '.join(transformed))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--repo',default='.');p.add_argument('--apply',action='store_true');a=p.parse_args()
 try:run(Path(a.repo).resolve(),a.apply)
 except (RuntimeError,subprocess.CalledProcessError,FileNotFoundError) as e:print(str(e),file=sys.stderr);sys.exit(2)
