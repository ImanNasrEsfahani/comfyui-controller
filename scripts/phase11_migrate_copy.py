#!/usr/bin/env python3
"""Safe additive Phase11 migration on a brand-new SQLite backup ONLY."""
from __future__ import annotations
import argparse,hashlib,importlib.util,os,sqlite3,sys,tempfile
from pathlib import Path

def sha(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for chunk in iter(lambda:f.read(2**20),b''):h.update(chunk)
 return h.hexdigest()

def copy_and_migrate(source,dest,root):
 source=Path(source).resolve();dest=Path(dest).resolve();root=Path(root).resolve()
 if not source.is_file() or source==dest or dest.exists():raise RuntimeError('Source missing, same path, or destination already exists')
 if not dest.parent.is_dir():raise RuntimeError('Destination directory missing')
 original=sha(source)
 spec=importlib.util.spec_from_file_location('phase11_copy_migration',root/'backend/app/migrations/phase11.py')
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 fd,temp=tempfile.mkstemp(dir=dest.parent,prefix='.phase11-copy-',suffix='.sqlite')
 os.close(fd)
 try:
  src=sqlite3.connect(f'file:{source}?mode=ro',uri=True)
  target=sqlite3.connect(temp)
  try:
   src.backup(target)
   target.commit()
   changed=mod.migrate(target)
   if list(target.execute('PRAGMA foreign_key_check')):raise RuntimeError('Foreign keys invalid')
   target.commit()
  finally:
   src.close();target.close()
  if sha(source)!=original:raise RuntimeError('Source file was modified during copy')
  os.chmod(temp,0o600);os.replace(temp,dest)
  return changed
 finally:
  if os.path.exists(temp):os.unlink(temp)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--destination',required=True);p.add_argument('--repo',default='.')
 a=p.parse_args()
 try:print('COPIED; migrated:',copy_and_migrate(a.source,a.destination,a.repo))
 except (OSError,RuntimeError,sqlite3.DatabaseError) as e:
  print('REFUSED:',type(e).__name__,str(e),file=sys.stderr);sys.exit(2)
