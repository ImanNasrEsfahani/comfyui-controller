"""Phase08 migration on a disposable SQLite backup of a disposable original fixture."""
from __future__ import annotations
import unittest,tempfile,sqlite3,hashlib
from pathlib import Path
from app.migrations.phase01 import migrate as m01
from app.migrations.phase02 import migrate as m02
from app.migrations.phase05 import migrate as m05
from app.migrations.phase07 import migrate as m07
from app.migrations.phase08 import migrate as m08
from test_phase06_media import LEGACY

class TestPhase08Migration(unittest.TestCase):
 def prep(self):
  tmp=tempfile.TemporaryDirectory();f=Path(tmp.name)/'source.db'
  with sqlite3.connect(f) as c:
   c.executescript(LEGACY);c.commit();m01(c);m02(c);m05(c);m07(c)
  return tmp,f
 def test_additive_idempotence_and_immutable_snapshot(self):
  t,f=self.prep()
  try:
   with sqlite3.connect(f) as c:
    self.assertTrue(m08(c));self.assertFalse(m08(c))
    self.assertFalse(list(c.execute('PRAGMA foreign_key_check')))
    self.assertIn('user_parameter_presets',{x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")})
  finally:t.cleanup()
 def test_missing_prerequisite_fail_closed(self):
  with sqlite3.connect(':memory:') as c:
   with self.assertRaises(RuntimeError):m08(c)
 def test_migration_copy_preserves_source_byte_hash(self):
  t,src=self.prep();dst=Path(t.name)/'copy.db'
  try:
   before=hashlib.sha256(src.read_bytes()).hexdigest()
   import importlib.util
   s=Path(__file__).resolve().parents[1]/'scripts/phase08_migrate_copy.py'
   spec=importlib.util.spec_from_file_location('copy08',s);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
   module.run(src,dst)
   self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(),before)
   with sqlite3.connect(dst) as c:self.assertEqual(c.execute("SELECT count(*) FROM schema_migrations WHERE revision='008_dynamic_parameters_loras_presets'").fetchone()[0],1)
   with self.assertRaises(RuntimeError):module.run(src,dst)
  finally:t.cleanup()
