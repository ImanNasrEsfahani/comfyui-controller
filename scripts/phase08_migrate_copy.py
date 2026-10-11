#!/usr/bin/env python3
"""WAL-safe SQLite online backup from named source to NEW target; migrate COPY only."""
from pathlib import Path
import sqlite3,sys,os,importlib.util,tempfile,argparse

def run(src:Path,target:Path):
 src=src.resolve();target=target.resolve()
 if not src.is_file() or target.exists() or src==target:raise RuntimeError('Source required; target must not exist')
 target.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix='.phase08-',suffix='.db',dir=target.parent);os.close(fd)
 try:
  with sqlite3.connect('file:'+str(src)+'?mode=ro',uri=True) as source,sqlite3.connect(tmp) as dest:source.backup(dest)
  path=Path(__file__).resolve().parents[1]/'backend/app/migrations/phase08.py'
  spec=importlib.util.spec_from_file_location('phase08_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  with sqlite3.connect(tmp) as db:module.migrate(db)
  os.replace(tmp,target)
  print('COPY CREATED',target.name,module.REVISION)
 except BaseException:
  try:os.unlink(tmp)
  except OSError:pass
  raise
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--target',type=Path,required=True);args=p.parse_args()
 try:run(args.source,args.target)
 except (OSError,RuntimeError,sqlite3.Error) as e:print('Refused:',e,file=sys.stderr);sys.exit(2)
