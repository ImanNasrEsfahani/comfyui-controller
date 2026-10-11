"""Offline SQLite migration rehearsal; never opens production DB."""
import unittest,sqlite3,tempfile,hashlib
from pathlib import Path
from test_phase06_media import LEGACY
from app.migrations.phase01 import migrate as m01
from app.migrations.phase02 import migrate as m02
from app.migrations.phase05 import migrate as m05
from app.migrations.phase07 import migrate as m07

class TestRegistryMigration(unittest.TestCase):
 def build(self):
  tmp=tempfile.TemporaryDirectory();src=Path(tmp.name)/'source.db'
  with sqlite3.connect(src) as c:
   c.executescript(LEGACY);c.commit();m01(c);m02(c);m05(c)
  return tmp,src
 def test_offline_additive_and_idempotent(self):
  t,p=self.build()
  try:
   with sqlite3.connect(p) as c:
    self.assertTrue(m07(c));self.assertFalse(m07(c))
    self.assertEqual(c.execute('SELECT COUNT(*) FROM deployment_variable_schema').fetchone()[0],5)
    self.assertFalse(list(c.execute('PRAGMA foreign_key_check')))
  finally:t.cleanup()
 def test_reject_unmigrated_database(self):
  with sqlite3.connect(':memory:') as c:
   with self.assertRaises(RuntimeError):m07(c)
 def test_sqlite_backup_source_unchanged(self):
  t,src=self.build();target=Path(t.name)/'phase07-copy.db'
  try:
   before=hashlib.sha256(src.read_bytes()).hexdigest()
   import sys
   from importlib.util import spec_from_file_location,module_from_spec
   script=Path(__file__).resolve().parents[1]/'scripts/phase07_migrate_copy.py'
   spec=spec_from_file_location('migrate_copy',script);mod=module_from_spec(spec);spec.loader.exec_module(mod)
   mod.run(src,target)
   self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(),before)
   with sqlite3.connect(target) as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM schema_migrations WHERE revision='007_model_image_registry'").fetchone()[0],1)
   with self.assertRaises(RuntimeError):mod.run(src,target)
  finally:t.cleanup()
if __name__=='__main__':unittest.main()
