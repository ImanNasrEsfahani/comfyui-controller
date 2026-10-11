"""Stage10 additive migration idempotency and SQLite backup isolation."""
import sys,unittest,sqlite3,tempfile,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.migrations import phase09,phase10
from scripts.phase10_migrate_copy import copy_and_migrate
class Migration(unittest.TestCase):
 def sample(self,path):
  c=sqlite3.connect(path);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
  for q in ('CREATE TABLE schema_migrations(revision TEXT PRIMARY KEY,applied_at TEXT,checksum TEXT)',
   'CREATE TABLE users(id TEXT PRIMARY KEY)', 'CREATE TABLE jobs(id TEXT PRIMARY KEY)',
   'CREATE TABLE workflows(id TEXT PRIMARY KEY)','CREATE TABLE model_versions(id TEXT PRIMARY KEY)',
   'CREATE TABLE model_deployment_compatibility(model_id TEXT)'):c.execute(q)
  c.execute("INSERT INTO users VALUES('A')");c.execute("INSERT INTO model_versions VALUES('model-1')");c.commit();phase09.migrate(c);return c
 def test_idempotent(self):
  with tempfile.TemporaryDirectory() as d:
   c=self.sample(Path(d)/'db.sqlite');self.assertTrue(phase10.migrate(c));self.assertFalse(phase10.migrate(c));self.assertEqual(list(c.execute('PRAGMA foreign_key_check')),[]);c.close()
 def test_copy_preserves_original(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'source.sqlite';dst=Path(d)/'copy.sqlite';c=self.sample(p);c.close();digest=hashlib.sha256(p.read_bytes()).hexdigest();self.assertTrue(copy_and_migrate(p,dst));self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),digest)
   with sqlite3.connect(dst) as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='studio_drafts'").fetchone()[0],1)
 def test_bad_destination_refused(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'source.sqlite';c=self.sample(p);c.close()
   with self.assertRaises(ValueError):copy_and_migrate(p,p)
   with self.assertRaises(ValueError):copy_and_migrate(p,Path(d)/'source.sqlite')
 def test_missing_phase09_fails_closed(self):
  with sqlite3.connect(':memory:') as c:
   with self.assertRaises(RuntimeError):phase10.migrate(c)
   self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='studio_drafts'").fetchone()[0],0)
if __name__=='__main__':unittest.main()
