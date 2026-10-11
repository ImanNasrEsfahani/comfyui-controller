#!/usr/bin/env python3
"""Safe, source-pinned local patch for backend/app/main.py; never writes GitHub."""
from __future__ import annotations
import hashlib
import subprocess
import sys
from pathlib import Path

BASE='3f749b52d375188e8844d68c42485db6668d928c'
MAIN_BLOB='f3fc84226be8704e4ae4d63b63babb84ca0ea291'


def blob_sha(content:bytes)->str:
    return hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()


def main(repo:Path)->None:
    path=repo/'backend/app/main.py'
    if not path.exists() or not (repo/'.git').exists():
        raise RuntimeError('Run from a complete git checkout')
    head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    if head!=BASE:
        raise RuntimeError(f'Checkout SHA does not match tested GitHub main ({BASE}); rebase and re-review required')
    data=path.read_bytes()
    if b'from .auth import router as auth_router' in data and b'app.include_router(auth_router)' in data:
        print('Already applied, no changes')
        return
    if blob_sha(data)!=MAIN_BLOB:
        raise RuntimeError('backend/app/main.py has unexpected changes; no files modified')
    old=b'from . import db, storage, salad, salad_control, job_lifecycle, settings_store, direct_queue, contracts\n'
    new=old+b'from .auth import router as auth_router\n'
    if data.count(old)!=1:
        raise RuntimeError('Import anchor mismatch')
    data=data.replace(old,new)
    anchor=b'app = FastAPI(title=settings.app_name, version="1.3.0")\n'
    if data.count(anchor)!=1:
        raise RuntimeError('App anchor mismatch')
    data=data.replace(anchor,anchor+b'app.include_router(auth_router)\n')
    path.write_bytes(data)
    print('Updated backend/app/main.py locally; diff and run regression suite before use')

if __name__=='__main__':
    try:main(Path(sys.argv[1] if len(sys.argv)>1 else '.').resolve())
    except (RuntimeError,subprocess.CalledProcessError) as exc:
        print(str(exc),file=sys.stderr)
        sys.exit(2)
