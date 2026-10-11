#!/usr/bin/env python3
"""Back up a local SQLite database safely; apply Phase13 only to a NEW COPY.

Never overwrite source or target. No app startup or production side effects.
"""
import argparse,hashlib,sqlite3,sys
from pathlib import Path
from importlib.util import spec_from_file_location,module_from_spec

def execute(source:Path,destination:Path,ack=False):
 if not ack:raise RuntimeError('Explicit --acknowledge-offline-copy is required')
 source=source.resolve();destination=destination.resolve()
 if source==destination or not source.is_file() or destination.exists():
  raise RuntimeError('Source must exist; destination must not exist and cannot equal source')
 destination.parent.mkdir(parents=True,exist_ok=True)
 with sqlite3.connect(f'file:{source.as_posix()}?mode=ro',uri=True) as s:
  with sqlite3.connect(destination) as d:s.backup(d)
 module_path=Path(__file__).resolve().parents[1]/'backend/app/migrations/phase13.py'
 spec=spec_from_file_location('migrate_v13',module_path);module=module_from_spec(spec);spec.loader.exec_module(module)
 try:
  with sqlite3.connect(destination) as d:
   applied=module.migrate(d)
   integrity=d.execute('PRAGMA integrity_check').fetchone()[0]
   fks=list(d.execute('PRAGMA foreign_key_check'))
   if integrity!='ok' or fks:raise RuntimeError('Integrity/FK validation failed')
  print('COPY ONLY: Phase13 migration '+('applied' if applied else 'already applied')+'; integrity OK')
 except Exception:
  destination.unlink(missing_ok=True)
  raise

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('destination',type=Path)
 p.add_argument('--acknowledge-offline-copy',action='store_true');a=p.parse_args()
 try:execute(a.source,a.destination,a.acknowledge_offline_copy)
 except Exception as e:print('REFUSED:',type(e).__name__,str(e),file=sys.stderr);sys.exit(2)
