#!/usr/bin/env python3
"""Read-only SQLite snapshot -> temporary restore -> integrity/owner audit.

Require an operator-provided, isolated, quiesced SQLite copy. No writes to source,
no upload, no persistent backup created by this tool. Results contain counts only.
"""
from __future__ import annotations
import argparse, hashlib, json, sqlite3, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

COUNT_TABLES=('users','jobs','input_assets','job_assets','assets','sessions','schema_migrations',
              'workflow_versions','job_attempts','instance_allocations','scheduler_usage_ledger')

def digest(path:Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while True:
            chunk=f.read(1024*1024)
            if not chunk:break
            h.update(chunk)
    return h.hexdigest()

def counts(c):
    tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    result={}
    for n in COUNT_TABLES:
        if n in tables:result[n]=c.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
    return result

def owners(c):
    tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    result={}
    for n in ('jobs','input_assets','job_assets','assets','instance_allocations'):
        if n not in tables:continue
        columns={r[1] for r in c.execute(f'PRAGMA table_info("{n}")')}
        owner='owner_user_id' if 'owner_user_id' in columns else 'owner_id' if 'owner_id' in columns else None
        if not owner:
            result[n]={'status':'BLOCKED','reason':'No owner column'}
            continue
        nulls=c.execute(f'SELECT COUNT(*) FROM "{n}" WHERE "{owner}" IS NULL OR TRIM("{owner}")=""').fetchone()[0]
        entry={'status':'FAIL' if nulls else 'PASS_SQL_ONLY','unassigned_count':nulls}
        if n=='jobs' and 'ownership_state' in columns:
            unknown=c.execute("SELECT COUNT(*) FROM jobs WHERE ownership_state IS NULL OR ownership_state!='verified'").fetchone()[0]
            entry.update(unverified_count=unknown,status='FAIL' if unknown or nulls else 'PASS_SQL_ONLY')
        result[n]=entry
    return result

def drill(source:Path,acknowledged=False)->dict:
    if not acknowledged:raise ValueError('Explicit --acknowledge-isolated-copy required')
    source=source.resolve(strict=True)
    if not source.is_file() or source.stat().st_size<100:raise ValueError('Invalid SQLite source')
    if Path(str(source)+'-wal').exists() or Path(str(source)+'-shm').exists():
        raise ValueError('Source must be a quiesced, checkpointed, isolated copy; WAL/SHM detected')
    before=digest(source)
    with tempfile.TemporaryDirectory(prefix='phase14-sqlite-restore-') as temp:
        target=Path(temp)/'restored.sqlite3'
        # mode=ro enforces no DB modifications, including by accidental SQL.
        uri='file:'+str(source).replace('?','%3F').replace('#','%23')+'?mode=ro'
        with sqlite3.connect(uri,uri=True) as original:
            with sqlite3.connect(target) as restored:
                original.backup(restored)
        with sqlite3.connect(uri,uri=True) as original,sqlite3.connect('file:'+str(target)+'?mode=ro',uri=True) as restored:
            c1=counts(original);c2=counts(restored)
            integrity=restored.execute('PRAGMA integrity_check').fetchone()[0]
            fk_count=len(restored.execute('PRAGMA foreign_key_check').fetchall())
            owner_audit=owners(restored)
            restore_hash=digest(target)
        after=digest(source)
    owner_bad=any(v['status']!='PASS_SQL_ONLY' for v in owner_audit.values())
    status='PASS_OFFLINE_ONLY' if before==after and c1==c2 and integrity=='ok' and fk_count==0 and not owner_bad else 'BLOCKED'
    return {'checked_at_utc':datetime.now(timezone.utc).isoformat(),'status':status,
            'source_unchanged':before==after,'count_parity':c1==c2,'counts':c2,
            'integrity_check':integrity,'foreign_key_violations':fk_count,
            'owner_audit':owner_audit,'source_sha256':before,'restored_sha256':restore_hash,
            'production_restore_verified':False,
            'note':'All checks on one supplied isolated copy; does not prove live R2 content, legacy mapping or production rollback'}

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',type=Path,required=True)
    ap.add_argument('--acknowledge-isolated-copy',action='store_true');ap.add_argument('--report',type=Path)
    a=ap.parse_args(argv)
    try:report=drill(a.source,a.acknowledge_isolated_copy)
    except (ValueError,OSError,sqlite3.DatabaseError) as e:
        print('REFUSED:',type(e).__name__,str(e),file=sys.stderr);return 2
    data=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(data)
    else:print(data,end='')
    return 0 if report['status']=='PASS_OFFLINE_ONLY' else 2
if __name__=='__main__':raise SystemExit(main())
