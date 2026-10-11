#!/usr/bin/env python3
"""Explicit Phase 01 database COPY/migration/inspection utilities.

Does NOT run during server startup; never accepts a production DB directly as
migration target. Provide an explicitly named disposable COPY path.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.migrations.phase01 import migrate,backup_copy,activate_scoped_idempotency,downgrade_empty_copy


def run(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='operation',required=True)
    back=sub.add_parser('backup-copy')
    back.add_argument('--source',type=Path,required=True)
    back.add_argument('--destination',type=Path,required=True)
    up=sub.add_parser('migrate-copy')
    up.add_argument('--copy',type=Path,required=True)
    down=sub.add_parser('downgrade-empty-copy')
    down.add_argument('--copy',type=Path,required=True)
    activate=sub.add_parser('activate-scoped-index')
    activate.add_argument('--copy',type=Path,required=True)
    activate.add_argument('--patched-job-records',type=Path,required=True)
    activate.add_argument('--patched-db',type=Path,required=True)
    args=p.parse_args(argv)
    if args.operation=='backup-copy':
        backup_copy(args.source,args.destination)
        print('Backup copy created and integrity-checked (no row content printed)')
        return 0
    if 'copy' not in args.copy.name.lower() and 'test' not in args.copy.name.lower():
        p.error('Migration target filename must include "copy" or "test"')
    if not args.copy.exists() or not args.copy.is_file():
        p.error('An existing isolated SQLite copy is required')
    conn=sqlite3.connect(f'file:{args.copy.resolve().as_posix()}?mode=rw',uri=True)
    try:
        with conn:
            r=(activate_scoped_idempotency(conn,patched_source=args.patched_job_records,patched_db_source=args.patched_db)
               if args.operation=='activate-scoped-index' else
               downgrade_empty_copy(conn) if args.operation=='downgrade-empty-copy' else migrate(conn))
        print(json.dumps(r,sort_keys=True))
    finally:
        conn.close()
    return 0


if __name__=='__main__':
    raise SystemExit(run())
