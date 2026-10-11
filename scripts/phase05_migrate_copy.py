#!/usr/bin/env python3
"""Manually migrate a disposable SQLite COPY. Never invoke automatically on startup."""
import argparse,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.migrations.phase05 import migrate

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db-copy',required=True,type=Path)
    p.add_argument('--acknowledge-offline-copy',action='store_true')
    a=p.parse_args()
    f=a.db_copy.resolve()
    if not a.acknowledge_offline_copy or not a.db_copy.is_file() or a.db_copy.is_symlink():
        p.error('Requires an existing isolated, non-symlink SQLite copy and --acknowledge-offline-copy')
    with sqlite3.connect(f) as c:
        first=migrate(c)
        checks=c.execute('PRAGMA integrity_check').fetchone()[0]
        fk=list(c.execute('PRAGMA foreign_key_check'))
        if checks!='ok' or fk:raise RuntimeError('Integrity check failed')
        print('Revision 005_account_admin:', 'applied' if first else 'already applied', '| integrity=ok | FK=ok')
if __name__=='__main__':main()
