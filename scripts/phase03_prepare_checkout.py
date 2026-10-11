#!/usr/bin/env python3
"""Generate main.py replacement only from an EXACT GitHub main checkout.

Does not touch GitHub, R2, Salad, SQLite or `.env`. Default is check/dry run;
explicit --apply is required. A newer HEAD or edited main.py aborts.
"""
from __future__ import annotations
import argparse
import hashlib
import subprocess
from pathlib import Path

BASE_COMMIT='2738df39a17b5f93c61ada6b955a56d121dc7101'
MAIN_BLOB='f3fc84226be8704e4ae4d63b63babb84ca0ea291'
RECORDS_BLOB='dce59a7979b86484bfed47e6b923a06a62c4d3ff'
IMPORT_ANCHOR='from . import db, storage, salad, salad_control, job_lifecycle, settings_store, direct_queue, contracts\n'
APP_ANCHOR='app = FastAPI(title=settings.app_name, version="1.3.0")\n'


def blobsha(text: str) -> str:
    raw=text.encode('utf-8')
    return hashlib.sha1(f'blob {len(raw)}'.encode()+b'\0'+raw).hexdigest()


def transform(code: str) -> str:
    if code.count(IMPORT_ANCHOR)!=1 or code.count(APP_ANCHOR)!=1:
        raise RuntimeError('Main.py anchors did not match the source contract')
    if 'from .owner_api import router as owner_router' in code:
        raise RuntimeError('Owner router already present; check changes manually')
    code=code.replace(IMPORT_ANCHOR,IMPORT_ANCHOR+
        'from .auth import router as auth_router\n'
        'from .owner_api import router as owner_router\n',1)
    code=code.replace(APP_ANCHOR,APP_ANCHOR+
        'app.include_router(auth_router)\n'
        '# Explicit opt-in ONLY. Shadow routes must precede legacy endpoints.\n'
        'if os.getenv("OWNER_ISOLATION_ENABLED", "false").lower() == "true":\n'
        '    app.include_router(owner_router)\n',1)
    return code


def transform_records(code: str) -> str:
    old="""def save_assets(c, assets):
    for asset in assets:
        fields = list(asset)
        c.execute("INSERT INTO job_assets(" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ") ON CONFLICT(job_id,storage_key) DO NOTHING", list(asset.values()))"""
    new="""def save_assets(c, assets):
    # Worker results inherit ownership from the persisted parent Job only.
    # Pre-Phase01 databases remain functional during opt-in migration.
    job_cols = {col["name"] for col in c.execute("PRAGMA table_info(jobs)")}
    asset_cols = {col["name"] for col in c.execute("PRAGMA table_info(job_assets)")}
    owner_schema = {"owner_user_id", "ownership_state"} <= job_cols and \
                   {"owner_user_id", "ownership_state"} <= asset_cols
    for asset in assets:
        record = {k:v for k,v in asset.items() if k not in {"owner_user_id","ownership_state"}}
        if owner_schema:
            row = c.execute("SELECT owner_user_id,ownership_state FROM jobs WHERE id=?",
                            (asset["job_id"],)).fetchone()
            if not row:
                raise ValueError("Output parent Job does not exist")
            record["owner_user_id"] = row["owner_user_id"]
            record["ownership_state"] = ("verified" if row["owner_user_id"]
                                           and row["ownership_state"]=="verified" else "unclaimed")
        fields=list(record)
        c.execute("INSERT INTO job_assets("+",".join(fields)+") VALUES ("+
                  ",".join("?" for _ in fields)+") ON CONFLICT(job_id,storage_key) DO NOTHING",
                  list(record.values()))"""
    if code.count(old)!=1:raise RuntimeError('job_records.save_assets anchor mismatch')
    return code.replace(old,new,1)


def apply(root: Path, write: bool):
    if not (root/'.git').is_dir():raise RuntimeError('Full .git checkout required')
    got=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    if got!=BASE_COMMIT:raise RuntimeError('HEAD changed since baseline: stop and re-review new GitHub main')
    p=root/'backend/app/main.py'
    original=p.read_text(encoding='utf-8')
    if blobsha(original)!=MAIN_BLOB:raise RuntimeError('Unexpected main.py blob SHA; refused to patch')
    rp=root/'backend/app/job_records.py'
    records=rp.read_text(encoding='utf-8')
    if blobsha(records)!=RECORDS_BLOB:raise RuntimeError('Unexpected job_records.py blob SHA; refused to patch')
    output=transform(original)
    new_records=transform_records(records)
    if write:
        p.write_text(output,encoding='utf-8')
        rp.write_text(new_records,encoding='utf-8')
        print('Generated full main.py and job_records.py replacements; review git diff and run CI.')
    else:print('Dry run PASS: HEAD and both Git blob hashes match; add --apply after staging review.')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--apply',action='store_true')
    a=parser.parse_args()
    try:apply(a.root.resolve(),a.apply)
    except (RuntimeError,subprocess.CalledProcessError) as exc:
        parser.exit(2,'ABORT: '+str(exc)+'\n')
