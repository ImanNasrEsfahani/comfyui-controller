#!/usr/bin/env python3
"""Local staging checkout integration. No GitHub writes; exact SHA and blob guard.

The ZIP contains full replacements for all changed frontend files. Only the
pre-existing 956-line main.py is expanded in place after source SHA verification.
"""
import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

BASE='1593039f9239db6e757b633b28477aa29d6a71c2'
MAIN_BLOB='f3fc84226be8704e4ae4d63b63babb84ca0ea291'
IMPORT_ANCHOR='from . import db, storage, salad, salad_control, job_lifecycle, settings_store, direct_queue, contracts\n'
APP_ANCHOR='app = FastAPI(title=settings.app_name, version="1.3.0")\n'
NEW_IMPORTS='from .auth import router as auth_router\nfrom .owner_api import router as owner_router\nfrom .account_api import router as account_router\n'
NEW_ROUTER='app.include_router(auth_router)\napp.include_router(owner_router)\napp.include_router(account_router)\n'

def blob(data:bytes)->str:
    return hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()

def integrate(root:Path,apply:bool=False):
    if not (root/'.git').exists():raise RuntimeError('A full clean local git checkout is required')
    head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    if head != BASE:raise RuntimeError(f'Wrong revision {head}; expected {BASE}. Rebuild package for newer main.')
    main=root/'backend/app/main.py'
    data=main.read_bytes()
    if NEW_IMPORTS.encode() in data and NEW_ROUTER.encode() in data:
        print('Phase02/03/05 routers already included; no further changes');return
    if blob(data)!=MAIN_BLOB:raise RuntimeError('main.py unexpected blob hash: refusing unreviewed replacement')
    text=data.decode('utf-8')
    if text.count(IMPORT_ANCHOR)!=1 or text.count(APP_ANCHOR)!=1:
        raise RuntimeError('main.py anchor mismatch; no modifications')
    for path in ['backend/app/auth.py','backend/app/owner_api.py','backend/app/account_api.py',
                 'backend/app/migrations/phase05.py','frontend/src/app/router.jsx']:
        if not (root/path).is_file():raise RuntimeError(f'Missing staged file {path}')
    text=text.replace(IMPORT_ANCHOR,IMPORT_ANCHOR+NEW_IMPORTS,1)
    text=text.replace(APP_ANCHOR,APP_ANCHOR+NEW_ROUTER,1)
    if apply:main.write_text(text)
    print('APPLIED locally' if apply else 'DRY RUN OK: main.py anchor + GitHub SHA verified; pass --apply')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',default='.')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    try:integrate(Path(args.repo).resolve(),args.apply)
    except (RuntimeError,subprocess.CalledProcessError) as e:print(str(e),file=sys.stderr);sys.exit(2)
