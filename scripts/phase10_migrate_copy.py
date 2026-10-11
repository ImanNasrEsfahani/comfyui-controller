#!/usr/bin/env python3
"""SQLite backup API -> TEMP COPY -> Phase10 migration -> atomic NEW TARGET only.

Never mutates/overwrites a source SQLite DB or existing target. Can read a live DB
through SQLite backup API, but use a controlled offline staging snapshot for QA.
"""
from __future__ import annotations
import argparse,sqlite3,sys,importlib.util,os,tempfile
from pathlib import Path

def copy_and_migrate(source:Path,dest:Path):
 source,dest=source.resolve(),dest.resolve()
 if not source.is_file() or source==dest or dest.exists():
  raise ValueError('Existing source and unused distinct copy target required')
 if not dest.parent.is_dir():raise ValueError('Destination directory must already exist')
 handle,tmp=tempfile.mkstemp(prefix='.phase10-',suffix='.sqlite',dir=dest.parent)
 os.close(handle)
 try:
  with sqlite3.connect(f'file:{source}?mode=ro',uri=True) as original:
   with sqlite3.connect(tmp) as output:original.backup(output)
  path=Path(__file__).resolve().parents[1]/'backend/app/migrations/phase10.py'
  spec=importlib.util.spec_from_file_location('phase10_migrate',path)
  mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
  with sqlite3.connect(tmp) as output:
   result=mod.migrate(output)
   if output.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
    raise RuntimeError('Copied SQLite integrity check failed')
  if dest.exists():raise RuntimeError('Refusing to overwrite an existing target after backup')
  os.replace(tmp,dest)
  return result
 finally:
  try:os.unlink(tmp)
  except FileNotFoundError:pass

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path);p.add_argument('--copy',required=True,type=Path);args=p.parse_args()
 try:
  copy_and_migrate(args.source,args.copy)
  print('Phase10 migration applied to NEW COPY. Source remained untouched.')
 except (RuntimeError,OSError,ValueError,sqlite3.Error) as e:print('REFUSED:',e,file=sys.stderr);sys.exit(2)
