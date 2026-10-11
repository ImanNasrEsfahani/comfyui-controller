#!/usr/bin/env python3
"""Opt-in additive migration ONLY on offline COPY path; refuses production DB."""
import argparse,os,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.migrations.phase06 import migrate
p=argparse.ArgumentParser();p.add_argument('--db-copy',required=True);p.add_argument('--acknowledge-offline-copy',action='store_true');a=p.parse_args()
path=Path(a.db_copy).resolve()
if not a.acknowledge_offline_copy or not path.is_file() or not any(x in path.name.lower() for x in ('copy','test','staging')):
 p.error('Offline/test COPY path + explicit acknowledgement required; no live DB permitted')
conn=sqlite3.connect(path);conn.row_factory=sqlite3.Row
try:
 changed=migrate(conn);integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
 fk=list(conn.execute('PRAGMA foreign_key_check'))
 print(f'changed={changed} integrity={integrity} fk_errors={len(fk)}')
 if integrity!='ok' or fk:sys.exit(2)
finally:conn.close()
