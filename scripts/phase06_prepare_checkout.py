#!/usr/bin/env python3
"""Phase06: SHA-guarded local installer. Never uses any GitHub write API."""
from __future__ import annotations
import argparse,hashlib,subprocess,sys,importlib.util
from pathlib import Path
BASE='f2932e390705631b899c47fc4d06567b09fd1bfc'
MAIN_BLOB='f3fc84226be8704e4ae4d63b63babb84ca0ea291'
RECORDS_BLOB='dce59a7979b86484bfed47e6b923a06a62c4d3ff'
IMPORT='from . import db, storage, salad, salad_control, job_lifecycle, settings_store, direct_queue, contracts\n'
APP='app = FastAPI(title=settings.app_name, version="1.3.0")\n'
NEW_IMPORT=('from .auth import router as auth_router\n'
 'from .owner_api import router as owner_router\n'
 'from .account_api import router as account_router\n'
 'from .media_api import router as media_router\n')
NEW_ROUTER=('app.include_router(auth_router)\n'
 'if os.getenv("MEDIA_LIBRARY_ENABLED", "false").lower() == "true":\n'
 '    app.include_router(media_router)\n'
 'if os.getenv("OWNER_ISOLATION_ENABLED", "false").lower() == "true":\n'
 '    app.include_router(owner_router)\n'
 'if os.getenv("ACCOUNT_UI_ENABLED", "false").lower() == "true":\n'
 '    app.include_router(account_router)\n')

def blob(data:bytes):return hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()
def transform(code:str):
 if code.count(IMPORT)!=1 or code.count(APP)!=1:raise RuntimeError('Original main.py anchors changed')
 return code.replace(IMPORT,IMPORT+NEW_IMPORT,1).replace(APP,APP+NEW_ROUTER,1)
def records_transform(code:str,script:Path):
 spec=importlib.util.spec_from_file_location('phase03_previous_patcher',script)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module.transform_records(code)

def run(root:Path,apply:bool):
 if not (root/'.git').is_dir():raise RuntimeError('Complete git checkout required')
 sha=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
 if sha!=BASE:raise RuntimeError('Main SHA changed; rebuild patch from latest GitHub HEAD')
 main=root/'backend/app/main.py';rec=root/'backend/app/job_records.py'
 if blob(main.read_bytes())!=MAIN_BLOB or blob(rec.read_bytes())!=RECORDS_BLOB:
  raise RuntimeError('Source blob mismatch; refusing to modify unreviewed source')
 for name in ['backend/app/media_api.py','backend/app/media_repository.py',
  'backend/app/migrations/phase06.py','backend/app/auth.py','backend/app/owner_api.py',
  'backend/app/account_api.py','scripts/phase03_prepare_checkout.py']:
  if not (root/name).is_file():raise RuntimeError('Missing '+name)
 data=transform(main.read_text(encoding='utf-8'))
 records=records_transform(rec.read_text(encoding='utf-8'),root/'scripts/phase03_prepare_checkout.py')
 if apply:main.write_text(data);rec.write_text(records)
 print('APPLIED to local checkout; inspect diff before running staging tests' if apply else 'DRY RUN PASS; pass --apply after review')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--repo',default='.');p.add_argument('--apply',action='store_true');a=p.parse_args()
 try:run(Path(a.repo).resolve(),a.apply)
 except (RuntimeError,subprocess.CalledProcessError) as e:print(str(e),file=sys.stderr);sys.exit(2)
