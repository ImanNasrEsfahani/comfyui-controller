import unittest,sqlite3,tempfile,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.migrations.phase09 import migrate
from scripts.phase09_migrate_copy import copy_and_migrate

class Migration(unittest.TestCase):
 def create(self,path):
  c=sqlite3.connect(path);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
  for sql in ["CREATE TABLE schema_migrations(revision TEXT PRIMARY KEY,applied_at TEXT,checksum TEXT)","CREATE TABLE users(id TEXT PRIMARY KEY)","CREATE TABLE jobs(id TEXT PRIMARY KEY)","CREATE TABLE workflows(id TEXT PRIMARY KEY)","CREATE TABLE model_versions(id TEXT PRIMARY KEY)","CREATE TABLE model_deployment_compatibility(model_id TEXT)"]:
   c.execute(sql)
  c.execute("INSERT INTO users VALUES('a')");c.execute("INSERT INTO model_versions VALUES('model')");c.commit();return c
 def test_copy_preserves_original(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'orig.sqlite';copy=Path(d)/'copy.sqlite'
   c=self.create(p);c.close();old=hashlib.sha256(p.read_bytes()).hexdigest()
   self.assertTrue(copy_and_migrate(p,copy));self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),old)
   with sqlite3.connect(copy) as s:self.assertIn('workflow_versions',[r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table'")])
 def test_idempotent_and_fk(self):
  with tempfile.TemporaryDirectory() as d:
   c=self.create(Path(d)/'db.sqlite')
   self.assertTrue(migrate(c));self.assertFalse(migrate(c));self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[]);c.close()
 def test_missing_prerequisite_rollback(self):
  with sqlite3.connect(':memory:') as c:
   with self.assertRaises(RuntimeError):migrate(c)
   self.assertEqual(c.execute("SELECT name FROM sqlite_master WHERE name='workflow_versions'").fetchone(),None)
 def test_bad_copy_target_refused(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'db.sqlite';c=self.create(p);c.close()
   with self.assertRaises(ValueError):copy_and_migrate(p,p)
   with self.assertRaises(ValueError):copy_and_migrate(p,Path(d)/'db.sqlite')
if __name__=='__main__':unittest.main()
