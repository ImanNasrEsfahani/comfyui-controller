#!/usr/bin/env python3
"""EXPLICIT, OFFLINE Phase02 migration: only accepts --copy; source is never opened for writing."""
from __future__ import annotations
import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.migrations.phase02 import migrate


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True,help='existing private SQLite snapshot')
    parser.add_argument('--copy',type=Path,required=True,help='fresh destination (must NOT already exist)')
    args=parser.parse_args()
    src=args.source.resolve(); dst=args.copy.resolve()
    if not src.is_file() or src==dst or dst.exists():
        parser.error('Source must exist; copy destination must be new and different')
    dst.parent.mkdir(parents=True,exist_ok=True)
    try:
        with sqlite3.connect(f'file:{src}?mode=ro',uri=True) as s, sqlite3.connect(dst) as d:
            s.backup(d)
        with sqlite3.connect(dst) as conn:
            changed=migrate(conn)
            bad=list(conn.execute('PRAGMA foreign_key_check'))
            assert not bad, 'Foreign keys invalid'
            print(json.dumps({'migrated':changed,'foreign_key_violations':0,'destination':str(dst)}))
    except BaseException:
        dst.unlink(missing_ok=True)
        raise

if __name__=='__main__': main()
