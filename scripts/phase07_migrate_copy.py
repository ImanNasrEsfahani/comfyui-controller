#!/usr/bin/env python3
"""Online SQLite backup of an explicitly nominated source to a NEW target; migrate target only."""
from pathlib import Path
import argparse,sqlite3,sys,os,importlib.util,tempfile

def run(src:Path,target:Path):
 src=src.resolve();target=target.resolve()
 if not src.is_file() or target.exists() or src==target:raise RuntimeError('Source must exist; target must NOT exist')
 target.parent.mkdir(parents=True,exist_ok=True)
 fd,temp=tempfile.mkstemp(prefix='.phase07-',suffix='.db',dir=target.parent);os.close(fd)
 try:
  with sqlite3.connect('file:'+str(src)+'?mode=ro',uri=True) as a,sqlite3.connect(temp) as b:a.backup(b)
  path=Path(__file__).resolve().parents[1]/'backend/app/migrations/phase07.py'
  spec=importlib.util.spec_from_file_location('phase07_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  with sqlite3.connect(temp) as db:module.migrate(db)
  os.replace(temp,target)
  print('NEW COPY CREATED:',target.name,'migration:',module.REVISION)
 except BaseException:
  try:os.unlink(temp)
  except OSError:pass
  raise
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--target',type=Path,required=True);a=p.parse_args()
 try:run(a.source,a.target)
 except (RuntimeError,sqlite3.Error,OSError) as e:print(e,file=sys.stderr);sys.exit(2)
