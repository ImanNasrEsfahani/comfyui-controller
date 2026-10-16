#!/usr/bin/env python3
"""SHA-guarded replacement builder for ComfyUI Controller October 16 main.

Run from checkout only after extracting this repair overlay. Generates three
complete modified source files in an output directory, without touching repo
until --apply. Refuses unknown source revisions. Creates no DB or GPU changes.
"""
from __future__ import annotations
import argparse
import hashlib
import os
import sys
from pathlib import Path

BASE = {
    'backend/app/owner_api.py': 'b666b941772842043a660f983bfac2f22ca424d0',
    'backend/app/job_records.py': 'dce59a7979b86484bfed47e6b923a06a62c4d3ff',
    'frontend/src/app/router.jsx': '0ee8fdae7ad71d88c7516ffec70d9bda2efb6a3b',
}


def blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def swap(source, old, new, path):
    if source.count(old)!=1:
        raise ValueError(f'{path}: exact anchored fragment missing or duplicated')
    return source.replace(old, new, 1)


def change_owner(s):
    s=swap(s,'from . import db, security, storage, owner_repository as owners',
        'from . import db, security, storage, owner_repository as owners\nfrom .contracts import JobIn\nfrom . import owner_direct_bridge as direct_bridge','owner_api')
    s=swap(s,'''        row=owners.job_for_request(c,user['user_id'],client_request_id)
        if row is None:denial()
        return output(row,c,user['user_id'])''',
    '''        row=owners.job_for_request(c,user['user_id'],client_request_id)
        if row is None:
            row=direct_bridge.lookup_by_client_key(user['user_id'],client_request_id)
        if row is None:denial()
        return output(row,c,user['user_id'])''','owner_api')
    s=swap(s,'''@router.post('/jobs')
def generate(request:Request,user=user_dep):
    security.require_csrf(request)
    # Legacy db.create_job() still has global request-key lookup and may race
    # Worker claim before owner is saved. Never submit an ownerless GPU Job.
    raise HTTPException(503,'Owner-safe job submission is not yet enabled')''',
    '''@router.get('/legacy-direct/workflows')
def legacy_direct_workflows(user=user_dep):
    return direct_bridge.workflow_catalog(user)


@router.post('/jobs')
def generate(request:Request,body:JobIn,user=user_dep):
    security.require_csrf(request)
    # Atomic owner is inserted before this Job becomes claimable; the legacy
    # non-owner-aware submit_job helper is never called.
    try:
        return direct_bridge.submit(user, body)
    except Exception as exc:
        from .contracts import ContractError
        if isinstance(exc,ContractError):
            raise HTTPException(exc.status,str(exc)) from exc
        raise''','owner_api')
    return s


def change_records(s):
    return swap(s,'''def save_assets(c, assets):
    for asset in assets:
        fields = list(asset)
        c.execute("INSERT INTO job_assets(" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ") ON CONFLICT(job_id,storage_key) DO NOTHING", list(asset.values()))''',
    '''def save_assets(c, assets):
    # Worker metadata never decides ownership. Legacy databases without
    # identity columns must continue to function during offline migration.
    job_cols = {r['name'] for r in c.execute('PRAGMA table_info(jobs)')}
    asset_cols = {r['name'] for r in c.execute('PRAGMA table_info(job_assets)')}
    has_owner = {'owner_user_id','ownership_state'} <= job_cols and \
                {'owner_user_id','ownership_state'} <= asset_cols
    for asset in assets:
        record = {key:value for key,value in asset.items() if key not in ('owner_user_id','ownership_state')}
        if has_owner:
            parent = c.execute('SELECT owner_user_id,ownership_state FROM jobs WHERE id=?',
                               (record['job_id'],)).fetchone()
            if not parent:
                raise ValueError('Output parent Job was not found')
            record['owner_user_id'] = parent['owner_user_id']
            record['ownership_state'] = ('verified' if parent['owner_user_id']
                                         and parent['ownership_state']=='verified' else 'unclaimed')
        fields = list(record)
        c.execute("INSERT INTO job_assets(" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ") ON CONFLICT(job_id,storage_key) DO NOTHING", list(record.values()))''',
    'job_records')


def change_router(s):
    s=swap(s,"import {ParameterStudio,PresetsPage} from '../pages/parameters/ParameterPages.jsx';",
      "import {ParameterStudio,PresetsPage} from '../pages/parameters/ParameterPages.jsx';\nimport {LegacyDirectPanel} from '../pages/legacy-direct/LegacyDirectPanel.jsx';",'router')
    s=swap(s,"node=<><ParameterStudio/><ReferenceDraftPanel/></>;",
      "node=<><LegacyDirectPanel/><ParameterStudio/><ReferenceDraftPanel/></>;",'router')
    return s


REWRITE={
  'backend/app/owner_api.py':change_owner,
  'backend/app/job_records.py':change_records,
  'frontend/src/app/router.jsx':change_router,
}

def prepare(root):
    result={}
    for path,func in REWRITE.items():
        raw=(root/path).read_bytes()
        if blob(raw)!=BASE[path]:
            raise ValueError(f'{path}: unexpected Git blob. Checkout latest reviewed commit first; do not overwrite changes. Actual={blob(raw)}')
        text=raw.decode('utf-8')
        result[path]=func(text).encode('utf-8')
    for name in ('backend/app/owner_direct_bridge.py','frontend/src/pages/legacy-direct/LegacyDirectPanel.jsx'):
        if not (root/name).is_file():
            raise ValueError(f'Missing overlay file {name}; unzip overlay in repository root')
    return result


def run(root,apply=False):
    replacements=prepare(root)
    for path,raw in replacements.items():
        compile(raw,path,'exec') if path.endswith('.py') else None
        if apply:
            (root/path).write_bytes(raw)
        print(('REPLACED ' if apply else 'WILL REPLACE ')+path+' sha256='+hashlib.sha256(raw).hexdigest())
    return 0


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,default=Path('.'))
    ap.add_argument('--apply',action='store_true')
    args=ap.parse_args()
    try:return run(args.repo.resolve(),args.apply)
    except (OSError,ValueError,UnicodeError,SyntaxError) as exc:
        print('SAFE STOP: '+str(exc),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
