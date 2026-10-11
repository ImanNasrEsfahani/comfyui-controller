#!/usr/bin/env python3
"""Generate FULL drop-in replacements of two legacy files IN THE LOCAL CHECKOUT.

The supplied GitHub sources are read-only through a connector. This utility
accepts ONLY exact known Git blob versions, and never modifies the GitHub repo.
It does not run migrations, touch databases, or deploy anything.

Invocation: python scripts/phase01_prepare_checkout.py --apply
"""
from pathlib import Path
import argparse
import hashlib

SHA={
    'backend/app/job_records.py': 'dce59a7979b86484bfed47e6b923a06a62c4d3ff',
    'backend/app/db.py': '4a6295fb9d6cea6affd147a3a22bbae94916c4f7',
}


def replace_exact(src,old,new):
    count=src.count(old)
    if count!=1:
        raise RuntimeError(f'Expected exactly one anchor but found {count}: {old[:65]}')
    return src.replace(old,new,1)


def patch_job_records(src):
    src=replace_exact(src,'''      CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_client_request ON jobs(client_request_id)
        WHERE client_request_id IS NOT NULL;
''','')
    anchor='''    allowed = " OR ".join("(OLD.state='"'''
    insert='''    # Phase01: bootstraps old standalone schemas and scoped schemas safely.
    # Global uniqueness is retained until the explicit copy-only activation.
    if "owner_user_id" in {r["name"] for r in c.execute("PRAGMA table_info(jobs)")}:
        c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_owner_request
              ON jobs(owner_user_id,client_request_id)
              WHERE owner_user_id IS NOT NULL AND client_request_id IS NOT NULL""")
        c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_legacy_request
              ON jobs(client_request_id)
              WHERE owner_user_id IS NULL AND client_request_id IS NOT NULL""")
    else:
        c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_client_request
              ON jobs(client_request_id) WHERE client_request_id IS NOT NULL""")

'''
    src=replace_exact(src,anchor,insert+anchor)
    src=replace_exact(src,'''    row = c.execute("SELECT id,request_hash,hidden FROM jobs WHERE client_request_id=?", (client_request_id,)).fetchone()''', '''    # Resolve the verified original operator only from server-side approval.
    # Non-legacy user identities are never selected by this controller API.
    if "owner_user_id" in {r["name"] for r in c.execute("PRAGMA table_info(jobs)")}:
        from .identity_repository import legacy_controller_owner
        original_owner = legacy_controller_owner(c)
        if original_owner:
            row = c.execute("SELECT id,request_hash,hidden FROM jobs WHERE client_request_id=? AND owner_user_id=?",
                            (client_request_id, original_owner)).fetchone()
        else:
            row = c.execute("SELECT id,request_hash,hidden FROM jobs WHERE client_request_id=? AND owner_user_id IS NULL",
                            (client_request_id,)).fetchone()
    else:
        row = c.execute("SELECT id,request_hash,hidden FROM jobs WHERE client_request_id=?", (client_request_id,)).fetchone()''')
    return src


def patch_db(src):
    src=replace_exact(src,'''        existing = job_records.acceptance(c, local_id, client_request_id, request_hash)
''','''        # Approved legacy ownership is read server-side, never from a browser.
        from .identity_repository import legacy_controller_owner
        controller_owner_id = legacy_controller_owner(c)
        existing = job_records.acceptance(c, local_id, client_request_id, request_hash)
''')
    src=replace_exact(src,'''                snapshot_json,client_request_id,request_hash,owner,source_job_id,queued_at,active_attempt_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''','''                snapshot_json,client_request_id,request_hash,owner,source_job_id,queued_at,active_attempt_id,owner_user_id,ownership_state)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''')
    src=replace_exact(src,'''                source_job_id, now if execution_mode == "direct" else None, attempt_id,
''','''                source_job_id, now if execution_mode == "direct" else None, attempt_id,
                controller_owner_id, "verified" if controller_owner_id else "unclaimed",
''')
    # Without migration, old job schema doesn't have owner columns; therefore
    # this replacement must only be applied AFTER a copy-tested Phase01 schema
    # migration and a coordinated backend restart/maintenance window.
    return src


def blob_sha(content):
    raw=content.encode('utf-8')
    return hashlib.sha1(f'blob {len(raw)}'.encode()+b'\x00'+raw).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',action='store_true')
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    args=p.parse_args()
    patches={}
    for rel,sha in SHA.items():
        source=(args.root/rel).read_text('utf-8')
        got=blob_sha(source)
        if got!=sha:
            raise SystemExit(f'ABORT: unexpected source revision of {rel}. Expected {sha}, got {got}; no files written')
        patches[rel]=(patch_job_records(source) if rel.endswith('job_records.py') else patch_db(source))
    if not args.apply:
        print('All expected source files matched pinned Git blobs; add --apply to update checkout')
        return
    for rel,contents in patches.items():
        (args.root/rel).write_text(contents,'utf-8')
        print('Updated local',rel,'— review git diff before release')


if __name__=='__main__':main()
