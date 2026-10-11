"""Offline Phase06 additive migration/CLI + guarded installer pure transform tests."""
import importlib.util,sqlite3,sys,tempfile,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.migrations.phase01 import migrate as migrate01
from app.migrations.phase02 import migrate as migrate02
from app.migrations.phase06 import migrate as migrate06
LEGACY='''
CREATE TABLE workflows(id TEXT PRIMARY KEY,name TEXT,api_prompt TEXT,created_at TEXT,updated_at TEXT);
CREATE TABLE jobs(id TEXT PRIMARY KEY,client_request_id TEXT,request_hash TEXT,request_json TEXT NOT NULL,state TEXT NOT NULL,hidden INTEGER DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,active_attempt_id TEXT);
CREATE TABLE input_assets(asset_id TEXT PRIMARY KEY,storage_key TEXT,mime_type TEXT,size_bytes INTEGER,width INTEGER,height INTEGER,created_at TEXT);
CREATE TABLE job_assets(asset_id TEXT PRIMARY KEY,job_id TEXT,attempt_id TEXT,storage_key TEXT,media_type TEXT,mime_type TEXT,status TEXT,width INTEGER,height INTEGER,size_bytes INTEGER,created_at TEXT);
'''
class MigrationRehearsal(unittest.TestCase):
 def test_opt_in_schema_copy_only_and_idempotent(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'media-test-copy.db'
   with sqlite3.connect(path) as c:
    c.executescript(LEGACY);c.commit();migrate01(c);migrate02(c)
    self.assertTrue(migrate06(c));self.assertFalse(migrate06(c))
    self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
    self.assertEqual(list(c.execute('PRAGMA foreign_key_check')),[])
 def test_cli_requires_ack_and_copy_name(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'safe-copy.db'
   with sqlite3.connect(path) as c:
    c.executescript(LEGACY);c.commit();migrate01(c);migrate02(c)
   base=[sys.executable,str(ROOT/'scripts/phase06_migrate_copy.py'),'--db-copy',str(path)]
   self.assertNotEqual(subprocess.run(base,capture_output=True).returncode,0)
   done=subprocess.run(base+['--acknowledge-offline-copy'],capture_output=True,text=True)
   self.assertEqual(done.returncode,0,done.stderr)
   self.assertIn('integrity=ok',done.stdout)
 def test_patcher_transform_anchor_strict(self):
  spec=importlib.util.spec_from_file_location('phase06_installer',ROOT/'scripts/phase06_prepare_checkout.py')
  x=importlib.util.module_from_spec(spec);spec.loader.exec_module(x)
  self.assertIn('app.include_router(media_router)',x.transform(x.IMPORT+x.APP))
  self.assertIn('OWNER_ISOLATION_ENABLED',x.transform(x.IMPORT+x.APP))
  with self.assertRaises(RuntimeError):x.transform('invalid')
  legacy='''def save_assets(c, assets):
    for asset in assets:
        fields = list(asset)
        c.execute("INSERT INTO job_assets(" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ") ON CONFLICT(job_id,storage_key) DO NOTHING", list(asset.values()))'''
  transformed=x.records_transform(legacy,ROOT/'scripts/phase03_prepare_checkout.py')
  self.assertIn('verified',transformed)
  compile(transformed,'<owner-inheritance-patch>','exec')
if __name__=='__main__':unittest.main()
